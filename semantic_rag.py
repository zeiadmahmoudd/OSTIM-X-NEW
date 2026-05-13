import os
import re
import pickle
import numpy as np
import faiss
import docx2txt
from sentence_transformers import SentenceTransformer

# =========================================================
# SMART UNIVERSITY - SEMANTIC RAG ENGINE
# =========================================================

# Put ALL knowledge base files here
DOC_FILES = [
    "Final database.docx",
    "Summary & expected Q of the Database.docx"
]

INDEX_FILE = "semantic_index.faiss"
CHUNKS_FILE = "semantic_chunks.pkl"

# Better semantic embedding model
MODEL_NAME = "BAAI/bge-large-en-v1.5"

# Lazy loading
_model = None


# =========================================================
# LOAD EMBEDDING MODEL
# =========================================================
def get_model():
    global _model

    if _model is None:
        _model = SentenceTransformer(MODEL_NAME)

    return _model


# =========================================================
# CLEAN TEXT
# =========================================================
def clean_text(text):
    text = text.replace("\xa0", " ")
    text = re.sub(r"\n\s*\n", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)

    return text.strip()


# =========================================================
# LOAD ALL DOCX FILES
# =========================================================
def load_all_documents():

    all_text = ""

    for file_name in DOC_FILES:

        file_path = os.path.join(os.getcwd(), file_name)

        if not os.path.exists(file_path):
            print(f"WARNING: {file_name} was not found.")
            continue

        try:
            text = docx2txt.process(file_path)
            text = clean_text(text)

            all_text += f"\n\n===== DOCUMENT: {file_name} =====\n\n"
            all_text += text

            print(f"Loaded: {file_name}")

        except Exception as e:
            print(f"Error loading {file_name}: {e}")

    return all_text


# =========================================================
# SMART STRUCTURED CHUNKING
# =========================================================
def split_into_structured_chunks(text):

    if not text:
        return []

    lines = text.splitlines()

    chunks = []
    current_chunk = []

    # Detect important academic sections
    patterns = [
        r"^[A-Z]{2,5}\s?-?\s?\d{3}",  # Course codes
        r"^Dr\.",
        r"^Prof\.",
        r"^Professor",
        r"^Research",
        r"^Career",
        r"^Question",
        r"^Answer",
        r"^WEX",
        r"^WAP",
        r"^Semester",
        r"^Academic",
        r"^Course",
    ]

    combined_pattern = re.compile("|".join(patterns), re.IGNORECASE)

    for line in lines:

        line = line.strip()

        if not line:
            continue

        # New important section
        if combined_pattern.search(line):

            if len(current_chunk) > 5:
                chunk_text = "\n".join(current_chunk)

                if len(chunk_text) > 100:
                    chunks.append(chunk_text)

                current_chunk = []

        current_chunk.append(line)

    # Last chunk
    if current_chunk:
        chunk_text = "\n".join(current_chunk)

        if len(chunk_text) > 100:
            chunks.append(chunk_text)

    # Fallback if chunking too small
    if len(chunks) < 10:

        words = text.split()

        chunks = []

        chunk_size = 220
        overlap = 50

        start = 0

        while start < len(words):

            end = start + chunk_size

            chunk = " ".join(words[start:end])

            if len(chunk.strip()) > 120:
                chunks.append(chunk)

            start += chunk_size - overlap

    return chunks


# =========================================================
# QUERY EXPANSION
# =========================================================
def expand_query(query):

    expanded = query

    replacements = {
        "AI": "Artificial Intelligence Machine Learning Deep Learning",
        "ML": "Machine Learning Artificial Intelligence",
        "blockchain": "blockchain distributed systems crypto",
        "prof": "professor instructor academic staff",
        "teacher": "professor instructor lecturer",
        "credits": "ECTS credits course credit",
        "course": "subject lecture module",
        "advisor": "supervisor professor thesis advisor",
        "career": "job profession industry role",
        "programming": "coding software development",
    }

    query_lower = query.lower()

    for key, value in replacements.items():

        if key.lower() in query_lower:
            expanded += " " + value

    return expanded


# =========================================================
# BUILD VECTOR DATABASE
# =========================================================
def build_semantic_index(force_rebuild=False):

    if (
        not force_rebuild
        and os.path.exists(INDEX_FILE)
        and os.path.exists(CHUNKS_FILE)
    ):
        print("Semantic index already exists.")
        return True

    print("Loading academic documents...")

    full_text = load_all_documents()

    if not full_text:
        raise ValueError("No readable text found in knowledge base documents.")

    print("Creating structured semantic chunks...")

    chunks = split_into_structured_chunks(full_text)

    if not chunks:
        raise ValueError("No semantic chunks were created.")

    print(f"Created {len(chunks)} semantic chunks.")

    model = get_model()

    print("Generating embeddings...")

    embeddings = model.encode(
        chunks,
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=True
    ).astype("float32")

    dimension = embeddings.shape[1]

    # FAISS similarity index
    index = faiss.IndexFlatIP(dimension)

    index.add(embeddings)

    # Save FAISS index
    faiss.write_index(index, INDEX_FILE)

    # Save chunks
    with open(CHUNKS_FILE, "wb") as f:
        pickle.dump(chunks, f)

    print("Semantic FAISS index built successfully.")

    return True


# =========================================================
# SEMANTIC SEARCH
# =========================================================
def semantic_search(query, top_k=6):

    build_semantic_index(force_rebuild=False)

    # Load FAISS
    index = faiss.read_index(INDEX_FILE)

    # Load chunks
    with open(CHUNKS_FILE, "rb") as f:
        chunks = pickle.load(f)

    model = get_model()

    # Expand query
    expanded_query = expand_query(query)

    # Embed query
    query_embedding = model.encode(
        [expanded_query],
        convert_to_numpy=True,
        normalize_embeddings=True
    ).astype("float32")

    # Search
    scores, indices = index.search(query_embedding, top_k)

    results = []

    for score, idx in zip(scores[0], indices[0]):

        if idx != -1:

            results.append({
                "score": float(score),
                "text": chunks[idx]
            })

    return results


# =========================================================
# RERANK RESULTS
# =========================================================
def rerank_results(query, results):

    query_words = set(query.lower().split())

    reranked = []

    for result in results:

        text_lower = result["text"].lower()

        keyword_bonus = 0

        for word in query_words:

            if word in text_lower:
                keyword_bonus += 0.03

        final_score = result["score"] + keyword_bonus

        reranked.append({
            "score": final_score,
            "text": result["text"]
        })

    reranked.sort(
        key=lambda x: x["score"],
        reverse=True
    )

    return reranked


# =========================================================
# FINAL CONTEXT RETRIEVAL
# =========================================================
def get_semantic_context(
    question,
    student=None,
    top_k=5,
    max_chars=6000
):

    try:

        results = semantic_search(question, top_k=top_k)

        if not results:
            return ""

        # Hybrid reranking
        results = rerank_results(question, results)

        context_parts = []

        for i, result in enumerate(results, start=1):

            context_parts.append(
                f"""
[Retrieved Context {i}]
Semantic Score: {result['score']:.3f}

{result['text']}
"""
            )

        context = "\n\n".join(context_parts)

        # Add student profile
        if student:

            student_context = f"""
========================
STUDENT PROFILE
========================

Name: {student.get("name")}
Department: {student.get("department")}
Semester: {student.get("semester")}
GPA: {student.get("gpa")}
Credits: {student.get("credits")}
Risk Level: {student.get("risk_level")}
Attendance: {student.get("attendance")}

========================
"""

            context = student_context + "\n\n" + context

        return context[:max_chars]

    except Exception as e:

        print(f"Semantic retrieval error: {e}")

        return ""


# =========================================================
# DEBUG TEST
# =========================================================
if __name__ == "__main__":

    print("Building Smart University Semantic RAG...")

    build_semantic_index(force_rebuild=True)

    while True:

        query = input("\nAsk question: ")

        if query.lower() == "exit":
            break

        context = get_semantic_context(query)

        print("\n================ CONTEXT ================\n")
        print(context[:4000])