import os
import shutil
from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from rag_engine import (
    process_pdf, ask_question, summarize_document,
    generate_quiz, generate_flashcards, list_uploaded_files, UPLOAD_DIR
)

app = FastAPI(title="Multi-PDF RAG Chatbot")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    question: str
    session_id: str = "default"


class FileRequest(BaseModel):
    filename: str


import traceback

@app.post("/upload")
async def upload_pdf(file: UploadFile = File(...)):
    try:
        file_path = os.path.join(UPLOAD_DIR, file.filename)
        with open(file_path, "wb") as f:
            shutil.copyfileobj(file.file, f)

        chunk_count = process_pdf(file_path, file.filename)
        return {"filename": file.filename, "chunks_indexed": chunk_count}
    except Exception as e:
        traceback.print_exc()
        return {"error": str(e), "trace": traceback.format_exc()}


@app.post("/chat")
async def chat(req: ChatRequest):
    result = ask_question(req.question, req.session_id)
    return result


@app.post("/summarize")
async def summarize(req: FileRequest):
    summary = summarize_document(req.filename)
    return {"summary": summary}


@app.post("/quiz")
async def quiz(req: FileRequest):
    quiz_json = generate_quiz(req.filename)
    return {"quiz": quiz_json}


@app.post("/flashcards")
async def flashcards(req: FileRequest):
    cards_json = generate_flashcards(req.filename)
    return {"flashcards": cards_json}


@app.get("/files")
async def files():
    return {"files": list_uploaded_files()}


@app.get("/")
async def root():
    return {"status": "Multi-PDF RAG Chatbot backend is running"}