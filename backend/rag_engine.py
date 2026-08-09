import os
import time
from dotenv import load_dotenv
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_google_genai import GoogleGenerativeAIEmbeddings, ChatGoogleGenerativeAI
from langchain_community.vectorstores import Chroma
from langchain.chains import ConversationalRetrievalChain
from langchain.memory import ConversationBufferMemory
 
from pathlib import Path
load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env")
 
CHROMA_DIR = "./chroma_db"
UPLOAD_DIR = "./uploaded_docs"
os.makedirs(UPLOAD_DIR, exist_ok=True)
 
embedding_model = GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001")
 
# Flash-Lite has a much higher free-tier daily cap than full Flash, but its
# per-minute cap is only 15 requests - see invoke_with_retry below for why
# that matters, and check https://ai.dev/rate-limit for your account's
# current exact numbers.
llm = ChatGoogleGenerativeAI(model="gemini-3.5-flash-lite", temperature=0.3)
 
vectorstore = Chroma(
    persist_directory=CHROMA_DIR,
    embedding_function=embedding_model,
    collection_name="pdf_collection"
)
 
_session_memories = {}
 
# Tracks background ingestion status per filename:
# "pending" | "done:<chunk_count>" | "error: <msg>"
processing_status = {}
 
# Caches so repeat clicks on the same file don't re-spend LLM quota.
_summary_cache = {}
_quiz_cache = {}
_flashcard_cache = {}
 
# Roughly 4 chars/token. Keep well under gemini-3.5-flash-lite's context
# window so one summarization call always fits in a single request.
MAX_SUMMARY_CHARS = 400_000
 
 
def get_memory(session_id: str) -> ConversationBufferMemory:
    if session_id not in _session_memories:
        _session_memories[session_id] = ConversationBufferMemory(
            memory_key="chat_history", return_messages=True, output_key="answer"
        )
    return _session_memories[session_id]
 
 
def invoke_with_retry(prompt: str, max_attempts: int = 3):
    """
    Wraps llm.invoke() with backoff on 429s. A single call can still get
    rate-limited if other requests hit the same minute window, so this
    retries with the delay Google suggests instead of failing immediately.
    """
    for attempt in range(max_attempts):
        try:
            return llm.invoke(prompt)
        except Exception as e:
            if "429" in str(e) or "ResourceExhausted" in str(e):
                if attempt < max_attempts - 1:
                    time.sleep(20)  # simple fixed backoff; quota resets per-minute
                    continue
            raise
 
 
def process_pdf(file_path: str, filename: str) -> int:
    """
    Loads, chunks, and embeds a PDF into the vectorstore.
    Batches embedding calls to stay under the free-tier rate limit
    (100 embed_content requests/minute). Only sleeps when an actual
    429 is hit, rather than pausing after every batch.
    """
    loader = PyPDFLoader(file_path)
    pages = loader.load()
 
    splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
    chunks = splitter.split_documents(pages)
 
    for c in chunks:
        c.metadata["source"] = filename
        c.metadata["page"] = c.metadata.get("page", 0) + 1
 
    batch_size = 90  # stay under the 100/min free-tier cap
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i:i + batch_size]
        for attempt in range(3):
            try:
                vectorstore.add_documents(batch)
                break
            except Exception as e:
                if "429" in str(e) and attempt < 2:
                    time.sleep(60)  # wait out the per-minute quota window
                else:
                    raise
 
    # A re-uploaded file should regenerate fresh summary/quiz/flashcards
    # next time they're requested, not serve stale cached ones.
    _summary_cache.pop(filename, None)
    _quiz_cache.pop(filename, None)
    _flashcard_cache.pop(filename, None)
 
    return len(chunks)
 
 
def process_pdf_background(file_path: str, filename: str) -> None:
    """
    Wrapper for use with FastAPI BackgroundTasks. Updates processing_status
    so the frontend can poll /status/{filename} instead of the upload
    request blocking until embedding finishes.
    """
    processing_status[filename] = "pending"
    try:
        chunk_count = process_pdf(file_path, filename)
        processing_status[filename] = f"done:{chunk_count}"
    except Exception as e:
        processing_status[filename] = f"error: {e}"
 
 
def get_processing_status(filename: str) -> str:
    return processing_status.get(filename, "unknown")
 
 
def ask_question(question: str, session_id: str):
    memory = get_memory(session_id)
    retriever = vectorstore.as_retriever(search_kwargs={"k": 4})
 
    chain = ConversationalRetrievalChain.from_llm(
        llm=llm,
        retriever=retriever,
        memory=memory,
        return_source_documents=True,
    )
 
    result = chain.invoke({"question": question})
 
    sources = []
    seen = set()
    for doc in result.get("source_documents", []):
        key = (doc.metadata.get("source"), doc.metadata.get("page"))
        if key not in seen:
            seen.add(key)
            sources.append({"file": key[0], "page": key[1]})
 
    return {"answer": result["answer"], "sources": sources}
 
 
def summarize_document(filename: str) -> str:
    """
    Single LLM call instead of a map_reduce chain. map_reduce called the
    LLM once per chunk, which fired dozens/hundreds of near-simultaneous
    requests on large PDFs and instantly blew the 15-requests-per-minute
    free tier cap. One call with the (safely truncated) full text avoids
    that entirely, since gemini-3.5-flash-lite's context window is large
    enough to hold most documents in one shot.
    """
    if filename in _summary_cache:
        return _summary_cache[filename]
 
    data = vectorstore.get(where={"source": filename})
    docs_text = data.get("documents", [])
    if not docs_text:
        return "No content found for this document."
 
    combined = "\n\n".join(docs_text)
    truncated = len(combined) > MAX_SUMMARY_CHARS
    if truncated:
        combined = combined[:MAX_SUMMARY_CHARS]
 
    prompt = f"""Summarize the following document clearly and concisely,
covering the main topics, key points, and overall structure.
{"Note: this document was too long to include in full - the summary covers only the first portion." if truncated else ""}
 
Content:
{combined}
"""
    response = invoke_with_retry(prompt)
    result = response.content
 
    _summary_cache[filename] = result
    return result
 
 
def generate_quiz(filename: str, num_questions: int = 5) -> str:
    cache_key = (filename, num_questions)
    if cache_key in _quiz_cache:
        return _quiz_cache[cache_key]
 
    data = vectorstore.get(where={"source": filename})
    docs_text = data.get("documents", [])
    combined = "\n\n".join(docs_text[:15])
 
    prompt = f"""Based on the following content, generate {num_questions} multiple-choice
quiz questions. Return ONLY valid JSON, a list of objects with keys:
"question", "options" (list of 4 strings), "answer" (the correct option string).
Do not include any text outside the JSON.
 
Content:
{combined}
"""
    response = invoke_with_retry(prompt)
    result = response.content
 
    _quiz_cache[cache_key] = result
    return result
 
 
def generate_flashcards(filename: str, num_cards: int = 8) -> str:
    cache_key = (filename, num_cards)
    if cache_key in _flashcard_cache:
        return _flashcard_cache[cache_key]
 
    data = vectorstore.get(where={"source": filename})
    docs_text = data.get("documents", [])
    combined = "\n\n".join(docs_text[:15])
 
    prompt = f"""Based on the following content, generate {num_cards} flashcards.
Return ONLY valid JSON, a list of objects with keys "term" and "definition".
Do not include any text outside the JSON.
 
Content:
{combined}
"""
    response = invoke_with_retry(prompt)
    result = response.content
 
    _flashcard_cache[cache_key] = result
    return result
 
 
def list_uploaded_files():
    data = vectorstore.get()
    sources = set(m.get("source") for m in data.get("metadatas", []) if m)
    return sorted(sources)
 