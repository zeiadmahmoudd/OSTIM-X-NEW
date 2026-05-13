import os
import requests
from dotenv import load_dotenv

load_dotenv()


# ---------------- AZURE OPENAI + AZURE SEARCH ----------------
def chat_with_rag(messages, use_rag=True):
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "").rstrip("/")
    deployment = os.getenv("OPENAI_DEPLOYMENT_NAME")
    api_key = os.getenv("AZURE_OPENAI_KEY")

    if not endpoint or not deployment or not api_key:
        return "Azure Connection Error: Missing Azure environment variables."

    url = f"{endpoint}/openai/deployments/{deployment}/chat/completions?api-version=2024-02-15-preview"

    headers = {
        "Content-Type": "application/json",
        "api-key": api_key
    }

    system_instruction = {
        "role": "system",
        "content": (
            "You are the OSTIM Technical University AI Academic Advisor. "
            "Use only the provided academic database. "
            "Answer clearly and professionally."
        )
    }

    clean_messages = [system_instruction] + [
        m for m in messages if m.get("role") != "system"
    ]

    payload = {
        "messages": clean_messages,
        "temperature": 0.0,
        "max_tokens": 1000
    }

    if use_rag:
        payload["data_sources"] = [{
            "type": "azure_search",
            "parameters": {
                "endpoint": os.getenv("AZURE_SEARCH_ENDPOINT"),
                "index_name": os.getenv("AZURE_SEARCH_INDEX"),
                "authentication": {
                    "type": "api_key",
                    "key": os.getenv("AZURE_SEARCH_KEY")
                },
                "strictness": 2,
                "in_scope": True,
                "query_type": "vector_simple_hybrid",
                "embedding_dependency": {
                    "type": "deployment_name",
                    "deployment_name": os.getenv("AZURE_EMBEDDING_DEPLOYMENT_NAME")
                }
            }
        }]

    try:
        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=30
        )

        data = response.json()

        if response.status_code == 200:
            content = data["choices"][0]["message"]["content"]
            return content.replace("[doc1]", "").replace("[doc2]", "").strip()

        return f"Azure Connection Error: {data.get('error', {}).get('message', 'Unknown Azure error')}"

    except Exception as e:
        return f"System Offline: {str(e)}"


# ---------------- GROQ PLAN B ----------------
def chat_with_groq(messages):
    try:
        from groq import Groq
    except Exception:
        return "Groq Error: Package not installed. Run: pip install groq"

    groq_key = os.getenv("GROQ_API_KEY")

    if not groq_key:
        return "Groq Error: Missing GROQ_API_KEY in .env file."

    try:
        client = Groq(api_key=groq_key)

        completion = client.chat.completions.create(
    model="llama-3.1-8b-instant",
    messages=messages,
    temperature=0.0,
    max_tokens=700
)

        return completion.choices[0].message.content

    except Exception as e:
        return f"Groq Error: {str(e)}"


# ---------------- FUTURE STUDENT DATA BACKEND ----------------
def get_student_data(username):
    """
    Future function for Azure/database integration.

    For now, app.py uses local SQLite student data.
    Later, when Azure/database is ready, this function can be updated
    to return real student data from the cloud backend.
    """

    return None