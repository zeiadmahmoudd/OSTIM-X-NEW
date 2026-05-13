import streamlit as st
from datetime import datetime
import sqlite3
import os
import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse
from dotenv import load_dotenv

load_dotenv()

try:
    from engine import chat_with_rag
except Exception:
    chat_with_rag = None

try:
    from engine import get_student_data as backend_get_student_data
except Exception:
    backend_get_student_data = None

try:
    from engine import chat_with_groq
except Exception:
    chat_with_groq = None

try:
    from semantic_rag import get_semantic_context, build_semantic_index
except Exception:
    get_semantic_context = None
    build_semantic_index = None

try:
    import PyPDF2
except Exception:
    PyPDF2 = None

try:
    import docx2txt
except Exception:
    docx2txt = None


st.set_page_config(
    page_title="Smart University",
    page_icon="🎓",
    layout="wide"
)


USE_AZURE_BACKEND = False
USE_GROQ_BACKEND = True
USE_LOCAL_DATABASE = True

COURSE_DATABASE_FILE = "Final database.docx"
DB_FILE = "students.db"
MAX_CONTEXT_CHARS = 3200


def get_connection():
    return sqlite3.connect(DB_FILE)


def grade_to_point(letter):
    mapping = {
        "AA": 4.0,
        "BA": 3.5,
        "BB": 3.0,
        "CB": 2.5,
        "CC": 2.0,
        "DC": 1.5,
        "DD": 1.0,
        "FD": 0.5,
        "FF": 0.0
    }
    return mapping.get(letter.upper(), 0.0)


def calculate_gpa(username):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT credits, grade_point
    FROM grades
    WHERE username = ?
    """, (username,))

    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return "0.00", "0", "0"

    total_credits = 0
    total_points = 0

    for credits, grade_point in rows:
        total_credits += int(credits)
        total_points += int(credits) * float(grade_point)

    gpa = total_points / total_credits if total_credits > 0 else 0
    completed_courses = len(rows)

    return f"{gpa:.2f}", str(total_credits), str(completed_courses)


def calculate_risk_level(gpa, attendance):
    try:
        gpa_float = float(gpa)
        attendance_float = float(attendance.replace("%", ""))
    except Exception:
        return "Medium"

    if gpa_float < 2.0 or attendance_float < 75:
        return "High"
    elif gpa_float < 2.7 or attendance_float < 85:
        return "Medium"
    return "Low"


def create_local_database():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS students (
        username TEXT PRIMARY KEY,
        password TEXT,
        name TEXT,
        student_id TEXT,
        department TEXT,
        semester TEXT,
        attendance TEXT,
        total_required TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS grades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT,
        course_code TEXT,
        course_name TEXT,
        credits INTEGER,
        grade_letter TEXT,
        grade_point REAL
    )
    """)

    default_students = [
        ("student", "123", "Connected Student", "STD-001", "Computer Engineering", "6", "89%", "24"),
        ("amira", "amira123", "Amira Abdallah", "STD-2026-001", "Computer Engineering", "6", "92%", "24"),
        ("ahmet", "ahmet123", "Ahmet Yilmaz", "STD-2026-002", "Software Engineering", "4", "71%", "24")
    ]

    for student in default_students:
        cursor.execute("""
        INSERT OR IGNORE INTO students VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, student)

    default_grades = [
        ("student", "CENG105", "Computer Programming I", 3, "BB", 3.0),
        ("student", "MATH101", "Engineering Mathematics I", 4, "CC", 2.0),
        ("student", "ENG101", "Academic English I", 3, "BA", 3.5),
        ("amira", "CENG105", "Computer Programming I", 3, "BA", 3.5),
        ("amira", "MATH101", "Engineering Mathematics I", 4, "BB", 3.0),
        ("amira", "ENG101", "Academic English I", 3, "AA", 4.0),
        ("ahmet", "CENG105", "Computer Programming I", 3, "CC", 2.0),
        ("ahmet", "MATH101", "Engineering Mathematics I", 4, "DD", 1.0),
        ("ahmet", "ENG101", "Academic English I", 3, "CB", 2.5)
    ]

    for grade in default_grades:
        cursor.execute("""
        SELECT id FROM grades
        WHERE username = ? AND course_code = ?
        """, (grade[0], grade[1]))

        if not cursor.fetchone():
            cursor.execute("""
            INSERT INTO grades (username, course_code, course_name, credits, grade_letter, grade_point)
            VALUES (?, ?, ?, ?, ?, ?)
            """, grade)

    conn.commit()
    conn.close()


def authenticate_user(username, password):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT username FROM students
    WHERE username = ? AND password = ?
    """, (username, password))

    result = cursor.fetchone()
    conn.close()

    return result is not None


def create_account(username, password, name):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT username FROM students WHERE username = ?", (username,))
    exists = cursor.fetchone()

    if exists:
        conn.close()
        return False

    student_id = f"STD-{datetime.now().strftime('%Y%m%d%H%M%S')}"

    cursor.execute("""
    INSERT INTO students VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        username,
        password,
        name,
        student_id,
        "Computer Engineering",
        "1",
        "0%",
        "24"
    ))

    conn.commit()
    conn.close()
    return True


def get_local_student_data(username):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM students WHERE username = ?", (username,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return {
            "username": username,
            "name": "Connected Student",
            "student_id": "STD-001",
            "department": "Computer Engineering",
            "semester": "1",
            "attendance": "0%",
            "total_required": "24",
            "gpa": "0.00",
            "credits": "0",
            "completed_courses": "0",
            "risk_level": "Medium",
            "progress": "0%"
        }

    gpa, credits, completed_courses = calculate_gpa(username)
    risk_level = calculate_risk_level(gpa, row[6])

    try:
        progress = int((int(completed_courses) / int(row[7])) * 100)
    except Exception:
        progress = 0

    return {
        "username": row[0],
        "name": row[2],
        "student_id": row[3],
        "department": row[4],
        "semester": row[5],
        "attendance": row[6],
        "total_required": row[7],
        "gpa": gpa,
        "credits": credits,
        "completed_courses": completed_courses,
        "risk_level": risk_level,
        "progress": f"{progress}%"
    }


def update_student_profile(username, name, department, semester, attendance):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
    UPDATE students
    SET name = ?, department = ?, semester = ?, attendance = ?
    WHERE username = ?
    """, (name, department, semester, attendance, username))

    conn.commit()
    conn.close()


def get_student_grades(username):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT id, course_code, course_name, credits, grade_letter, grade_point
    FROM grades
    WHERE username = ?
    ORDER BY course_code
    """, (username,))

    rows = cursor.fetchall()
    conn.close()

    return rows


def add_grade(username, course_code, course_name, credits, grade_letter):
    conn = get_connection()
    cursor = conn.cursor()

    point = grade_to_point(grade_letter)

    cursor.execute("""
    INSERT INTO grades (username, course_code, course_name, credits, grade_letter, grade_point)
    VALUES (?, ?, ?, ?, ?, ?)
    """, (
        username,
        course_code.upper(),
        course_name,
        int(credits),
        grade_letter.upper(),
        point
    ))

    conn.commit()
    conn.close()


def delete_grade(grade_id):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM grades WHERE id = ?", (grade_id,))

    conn.commit()
    conn.close()


def get_all_students():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT username, name, student_id, department, semester, attendance
    FROM students
    ORDER BY username
    """)

    rows = cursor.fetchall()
    conn.close()

    return rows


def delete_student(username):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM grades WHERE username = ?", (username,))
    cursor.execute("DELETE FROM students WHERE username = ?", (username,))

    conn.commit()
    conn.close()


create_local_database()


def load_course_database():
    if docx2txt is None:
        return ""

    file_path = os.path.join(os.getcwd(), COURSE_DATABASE_FILE)

    if not os.path.exists(file_path):
        return ""

    try:
        text = docx2txt.process(file_path)
        text = text.replace("\xa0", " ")
        text = re.sub(r"\n\s*\n", "\n", text)
        return text.strip()
    except Exception:
        return ""


def normalize_text(text):
    return re.sub(r"[^A-Z0-9]", "", text.upper())


def split_database_by_courses(database_text):
    if not database_text:
        return []

    text = database_text.replace("\xa0", " ")
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    sections = []
    current_section = []
    course_start_pattern = re.compile(r"\b[A-Z]{2,5}\s*-?\s*\d{3}\b")

    for line in lines:
        if course_start_pattern.search(line.upper()) and len(current_section) > 8:
            sections.append("\n".join(current_section))
            current_section = [line]
        else:
            current_section.append(line)

    if current_section:
        sections.append("\n".join(current_section))

    return sections


def keyword_fallback_search(question, database_text):
    if not database_text:
        return ""

    question_upper = question.upper()
    course_match = re.search(r"\b[A-Z]{2,5}\s*-?\s*\d{3}\b", question_upper)
    course_code = course_match.group(0) if course_match else None
    sections = split_database_by_courses(database_text)

    if course_code:
        normalized_course = normalize_text(course_code)

        for section in sections:
            if normalized_course in normalize_text(section):
                return section[:MAX_CONTEXT_CHARS]

    stop_words = {
        "what", "about", "tell", "me", "the", "and", "for", "with",
        "this", "that", "course", "please", "information", "give",
        "is", "are", "to", "of", "in", "on", "can", "you", "how",
        "many", "credit", "credits", "ects"
    }

    question_words = [
        word.lower().strip(".,?!:;()[]")
        for word in question.split()
        if len(word) > 2 and word.lower() not in stop_words
    ]

    scored_sections = []

    for section in sections:
        section_lower = section.lower()
        score = sum(1 for word in question_words if word in section_lower)

        if score > 0:
            scored_sections.append((score, section))

    scored_sections.sort(reverse=True, key=lambda x: x[0])

    if scored_sections:
        return scored_sections[0][1][:MAX_CONTEXT_CHARS]

    return ""


def get_best_context(question, student=None):
    if get_semantic_context is not None:
        try:
            context = get_semantic_context(
                question,
                student=student,
                top_k=4,
                max_chars=MAX_CONTEXT_CHARS
            )

            if context and len(context.strip()) > 30:
                return context, "Semantic FAISS RAG"
        except Exception:
            pass

    database_text = load_course_database()
    context = keyword_fallback_search(question, database_text)

    if context and len(context.strip()) > 30:
        return context, "Keyword fallback search"

    return "", "No context found"


def is_valid_url(url):
    try:
        parsed = urlparse(url)
        return parsed.scheme in ["http", "https"] and parsed.netloc != ""
    except Exception:
        return False


def scrape_website_text(url):
    if not is_valid_url(url):
        return "", "Invalid URL. Please enter a valid http or https URL."

    try:
        headers = {"User-Agent": "SmartUniversityAcademicAdvisor/1.0"}
        response = requests.get(url, headers=headers, timeout=10)

        if response.status_code != 200:
            return "", f"Could not access the page. Status code: {response.status_code}"

        content_type = response.headers.get("Content-Type", "")

        if "text/html" not in content_type:
            return "", "This URL does not seem to contain an HTML webpage."

        soup = BeautifulSoup(response.text, "html.parser")

        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()

        title = soup.title.string.strip() if soup.title and soup.title.string else "No title found"

        paragraphs = []

        for element in soup.find_all(["h1", "h2", "h3", "p", "li"]):
            text = element.get_text(separator=" ", strip=True)
            if text and len(text) > 25:
                paragraphs.append(text)

        extracted_text = "\n".join(paragraphs)

        if not extracted_text:
            return "", "No readable text found on this webpage."

        extracted_text = f"Page title: {title}\n\n{extracted_text}"
        return extracted_text[:8000], None

    except requests.exceptions.Timeout:
        return "", "The webpage took too long to respond."
    except requests.exceptions.RequestException as e:
        return "", f"Web request error: {str(e)}"
    except Exception as e:
        return "", f"Scraping error: {str(e)}"


def generate_answer_with_groq(question, context, student=None):

    if not context or len(context.strip()) < 20:
        return """
I could not find this information in the academic database.
Please try asking with more details or use a course code such as CENG 105, ENG 101, MATH 201, WEX 428, etc.
"""

    if chat_with_groq is None or not os.getenv("GROQ_API_KEY"):
        return f"""
Groq is not available.

Relevant context found:

{context[:MAX_CONTEXT_CHARS]}
"""

    student_info = ""

    if student:
        student_info = f"""
Student profile:
Name: {student.get("name")}
Department: {student.get("department")}
Semester: {student.get("semester")}
GPA: {student.get("gpa")}
Credits: {student.get("credits")}
Risk Level: {student.get("risk_level")}
Attendance: {student.get("attendance")}
"""

    messages = [
        {
            "role": "system",
            "content": """
You are Smart University AI Academic Advisor.

IMPORTANT RULES:

1. Use ONLY the retrieved academic context as your knowledge source.
2. Do NOT invent facts, titles, companies, or information not present in the context.
3. You MAY naturally paraphrase and explain the information in a more conversational and student-friendly way.
4. Do NOT copy-paste the context word-for-word unless necessary.
5. Answer like a helpful university academic advisor speaking naturally to a student.
6. Keep the answer grounded in the retrieved context.
7. If the information is unclear or missing, say:
"This information is not available in the academic database."
8. You can explain WHY something is important if it logically follows from the retrieved context.
9. Keep answers clear, concise, professional, and human-like.
"""
        },

        {
            "role": "user",
            "content": f"""
Student question:
{question}

{student_info}

Retrieved academic context:
{context[:MAX_CONTEXT_CHARS]}

Use the retrieved context as the ONLY knowledge source.
You may paraphrase naturally and explain concepts conversationally,
but do not invent information outside the academic database.
If the context identifies one professor/course/date/career related to the question, answer with only that item and explain using the exact reason written in the context.
"""
        }
    ]

    try:
        response = chat_with_groq(messages)

        if not response or len(response.strip()) == 0:
            return "No response was generated."

        return response.strip()

    except Exception as e:
        return f"""
Groq Error: {str(e)}

Retrieved Context:

{context[:MAX_CONTEXT_CHARS]}
"""

    student_info = ""

    if student:
        student_info = f"""
Student profile:
Name: {student.get("name")}
Department: {student.get("department")}
Semester: {student.get("semester")}
GPA: {student.get("gpa")}
Credits: {student.get("credits")}
Risk Level: {student.get("risk_level")}
Attendance: {student.get("attendance")}
"""

    messages = [
        {
            "role": "system",
            "content": """
You are Smart University AI Academic Advisor.
You MUST answer only using the provided academic database context.
Do not use outside knowledge.
Do not invent details.
If the answer is not clearly supported by the context, say that it is not available in the provided academic database.
Use a natural, helpful, student-friendly tone.
If the student profile is relevant, personalize the advice carefully.
"""
        },
        {
            "role": "user",
            "content": f"""
Student question:
{question}

{student_info}

Retrieved academic context:
{context[:MAX_CONTEXT_CHARS]}

Answer based only on this context.
"""
        }
    ]

    try:
        return chat_with_groq(messages)
    except Exception as e:
        return f"""
Groq Error: {str(e)}

Context found:

{context[:MAX_CONTEXT_CHARS]}
"""


def generate_answer_with_azure_first(question, context, student=None):
    if not context or len(context.strip()) < 20:
        return """
I could not find enough information in the academic database.
Please try asking with more details or use a course code such as CENG 105, ENG 101, MATH 201, WEX 428, etc.
"""

    student_info = ""

    if student:
        student_info = f"""
Student profile:
Name: {student.get("name")}
Department: {student.get("department")}
Semester: {student.get("semester")}
GPA: {student.get("gpa")}
Credits: {student.get("credits")}
Risk Level: {student.get("risk_level")}
Attendance: {student.get("attendance")}
"""

    messages = [
        {
            "role": "user",
            "content": f"""
Student question:
{question}

{student_info}

Retrieved academic context:
{context[:MAX_CONTEXT_CHARS]}

Please answer clearly and professionally based only on the provided academic database context.
"""
        }
    ]

    if USE_AZURE_BACKEND and chat_with_rag is not None:
        try:
            azure_response = chat_with_rag(messages, use_rag=True)

            if (
                azure_response
                and azure_response.strip()
                and "Azure Connection Error" not in azure_response
                and "System Offline" not in azure_response
                and "error" not in azure_response.lower()
                and "not available" not in azure_response.lower()
            ):
                return azure_response
        except Exception:
            pass

    if USE_GROQ_BACKEND:
        return generate_answer_with_groq(question, context, student)

    return f"""
Based on the academic database, here is the relevant information:

{context[:MAX_CONTEXT_CHARS]}
"""


def generate_uploaded_doc_summary_with_groq(extracted_text):
    if not extracted_text:
        return "No readable text was found."

    safe_text = extracted_text[:3500]

    if chat_with_groq is None or not os.getenv("GROQ_API_KEY"):
        return f"""
Local summary:
The uploaded document contains approximately {len(extracted_text.split())} words.
The system successfully extracted readable text from the file.
"""

    messages = [
        {
            "role": "system",
            "content": """
You are a study assistant for university students.
Summarize documents clearly and simply.
Focus on key concepts, definitions, course topics, and exam revision points.
"""
        },
        {
            "role": "user",
            "content": f"""
Summarize this document for a student:

{safe_text}
"""
        }
    ]

    try:
        return chat_with_groq(messages)
    except Exception as e:
        return f"Groq Error: {str(e)}"


def generate_uploaded_doc_summary_with_azure_first(extracted_text):
    if not extracted_text:
        return "No readable text was found."

    safe_text = extracted_text[:3500]

    if USE_AZURE_BACKEND and chat_with_rag is not None:
        try:
            messages = [
                {
                    "role": "user",
                    "content": f"""
Summarize this document in clear, simple, student-friendly language.

Document:
{safe_text}
"""
                }
            ]

            azure_summary = chat_with_rag(messages, use_rag=False)

            if azure_summary and "error" not in azure_summary.lower():
                return azure_summary
        except Exception:
            pass

    if USE_GROQ_BACKEND:
        return generate_uploaded_doc_summary_with_groq(safe_text)

    return f"""
Local summary:
The uploaded document contains approximately {len(extracted_text.split())} words.
"""


if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

if "username" not in st.session_state:
    st.session_state.username = ""

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

if "show_admin" not in st.session_state:
    st.session_state.show_admin = False


def load_student_data(username):
    if backend_get_student_data is not None and USE_AZURE_BACKEND:
        try:
            data = backend_get_student_data(username)
            if data:
                return data
        except Exception:
            pass

    return get_local_student_data(username)

 
st.markdown("""
<style>

/* MAIN PAGE */
.stApp {
    background-color: #f4f7fb !important;
    color: #111827 !important;
}

/* SIDEBAR */
section[data-testid="stSidebar"] {
    background-color: #111827 !important;
    width: 290px !important;
}

section[data-testid="stSidebar"] * {
    color: white !important;
}

/* Remove radio circles */
section[data-testid="stSidebar"] [data-testid="stRadio"] div[role="radiogroup"] > label > div:first-child {
    display: none !important;
}

section[data-testid="stSidebar"] [data-testid="stRadio"] label {
    padding: 14px 16px !important;
    border-radius: 12px !important;
    margin-bottom: 8px !important;
    cursor: pointer !important;
}

section[data-testid="stSidebar"] [data-testid="stRadio"] label:hover {
    background-color: #1f2937 !important;
}

/* TITLES */
.sidebar-title {
    color: white !important;
    font-size: 26px !important;
    font-weight: bold !important;
    text-align: center !important;
    margin-top: 10px !important;
    margin-bottom: 25px !important;
}

.big-title {
    color: #111827 !important;
    font-size: 38px !important;
    font-weight: bold !important;
}

.small-text {
    color: #374151 !important;
    font-size: 16px !important;
    font-weight: 500 !important;
}

/* PROFILE BOX */
.box {
    background-color: #111827 !important;
    color: white !important;
    padding: 20px !important;
    border-radius: 16px !important;
    box-shadow: 0 4px 12px rgba(0,0,0,0.12) !important;
    margin-top: 10px !important;
}

.box * {
    color: white !important;
}

/* CARDS */
.card {
    background-color: #111827 !important;
    color: white !important;
    padding: 16px !important;
    border-radius: 16px !important;
    text-align: center !important;
    box-shadow: 0 4px 12px rgba(0,0,0,0.12) !important;
}

.card * {
    color: white !important;
}

.card h4 {
    color: #e5e7eb !important;
    font-size: 15px !important;
}

.card h1 {
    color: white !important;
    font-size: 26px !important;
}

/* RESPONSE BOX */
.response-box {
    background-color: #111827 !important;
    color: white !important;
    padding: 18px !important;
    border-radius: 16px !important;
    box-shadow: 0 4px 12px rgba(0,0,0,0.12) !important;
    margin-top: 15px !important;
    line-height: 1.7 !important;
    white-space: pre-wrap !important;
}

.response-box * {
    color: white !important;
}

/* EXPANDERS */
[data-testid="stExpander"] {
    background-color: white !important;
    color: #111827 !important;
    border-radius: 10px !important;
    border: 1px solid #d1d5db !important;
}

[data-testid="stExpander"] * {
    color: #111827 !important;
}

/* INPUTS */
input, textarea {
    background-color: white !important;
    color: #111827 !important;
    border: 1px solid #d1d5db !important;
}

label, .stTextInput label, .stSelectbox label, .stNumberInput label {
    color: #111827 !important;
    font-weight: 600 !important;
}

/* TABLES */
table, th, td {
    color: #111827 !important;
    background-color: white !important;
}

/* BUTTONS */
.stButton button {
    background-color: #2563eb !important;
    color: white !important;
    border-radius: 10px !important;
    border: none !important;
    font-weight: 600 !important;
}

.stButton button:hover {
    background-color: #1d4ed8 !important;
    color: white !important;
}

/* ALERTS */
[data-testid="stAlert"] * {
    color: #111827 !important;
}

/* LOGIN BOX */
.login-box {
    background: white !important;
    color: #111827 !important;
    padding: 35px !important;
    border-radius: 18px !important;
    box-shadow: 0 4px 14px rgba(0,0,0,0.08) !important;
    max-width: 450px !important;
    margin: auto !important;
    margin-top: 80px !important;
}

.login-box * {
    color: #111827 !important;
}

</style>
""", unsafe_allow_html=True)


if not st.session_state.logged_in:
    st.markdown("""
    <div class="login-box">
        <h1 style="text-align:center;">🎓 Smart University</h1>
        <p style="text-align:center;color:#6b7280;">AI Academic Advisor Platform</p>
    </div>
    """, unsafe_allow_html=True)

    login_tab, create_tab = st.tabs(["Login", "Create Account"])

    with login_tab:
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")

        if st.button("Login"):
            if not username or not password:
                st.error("Please enter username and password.")
            elif authenticate_user(username, password):
                st.session_state.logged_in = True
                st.session_state.username = username
                st.success("Login successful.")
                st.rerun()
            else:
                st.error("Invalid username or password.")

    with create_tab:
        new_username = st.text_input("New Username")
        new_password = st.text_input("New Password", type="password")
        new_name = st.text_input("Full Name")

        if st.button("Create Account"):
            if not new_username or not new_password or not new_name:
                st.warning("Please fill all fields.")
            else:
                success = create_account(new_username, new_password, new_name)

                if success:
                    st.success("Account created successfully. You can login now.")
                else:
                    st.error("Username already exists.")

    st.stop()


st.sidebar.markdown(
    '<div class="sidebar-title">🎓 Smart University</div>',
    unsafe_allow_html=True
)

menu_items = [
    "🏠 Dashboard",
    "💬 Academic Advisor",
    "📚 Study Assistant",
    "⚙️ Settings",
    "🚪 Logout"
]

if st.session_state.show_admin:
    menu_items.append("🔐 Admin Dashboard")

page = st.sidebar.radio("", menu_items, label_visibility="collapsed")

admin_password = st.sidebar.text_input("Staff / Admin Access", type="password")

if admin_password == "admin123":
    st.session_state.show_admin = True
    st.sidebar.success("Admin mode activated")


if page == "🏠 Dashboard":
    student = load_student_data(st.session_state.username)

    st.markdown('<div class="big-title">Dashboard</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="small-text">Welcome back, {student["name"]} 👋</div>',
        unsafe_allow_html=True
    )

    st.markdown(f"""
    <div class="box">
        <h3>Student Profile</h3>
        <p><b>Name:</b> {student["name"]}</p>
        <p><b>Student ID:</b> {student["student_id"]}</p>
        <p><b>Department:</b> {student["department"]}</p>
        <p><b>Semester:</b> {student["semester"]}</p>
    </div>
    """, unsafe_allow_html=True)

    with st.expander("Edit Student Profile"):
        updated_name = st.text_input("Name", value=student["name"])
        updated_department = st.text_input("Department", value=student["department"])
        updated_semester = st.text_input("Semester", value=student["semester"])
        updated_attendance = st.text_input("Attendance", value=student["attendance"])

        if st.button("Update Profile"):
            update_student_profile(
                st.session_state.username,
                updated_name,
                updated_department,
                updated_semester,
                updated_attendance
            )
            st.success("Profile updated successfully.")
            st.rerun()

    c1, c2, c3, c4 = st.columns(4)

    with c1:
        st.markdown(f"""<div class="card"><h4>GPA</h4><h1>{student["gpa"]}</h1></div>""", unsafe_allow_html=True)

    with c2:
        st.markdown(f"""<div class="card"><h4>Credits</h4><h1>{student["credits"]}</h1></div>""", unsafe_allow_html=True)

    with c3:
        st.markdown(f"""<div class="card"><h4>Risk Level</h4><h1>{student["risk_level"]}</h1></div>""", unsafe_allow_html=True)

    with c4:
        st.markdown(f"""<div class="card"><h4>Attendance</h4><h1>{student["attendance"]}</h1></div>""", unsafe_allow_html=True)

    st.subheader("Grades & Automatic GPA")
    grades = get_student_grades(st.session_state.username)

    if grades:
        st.table([
            {
                "Course Code": row[1],
                "Course Name": row[2],
                "Credits": row[3],
                "Grade": row[4],
                "Point": row[5]
            }
            for row in grades
        ])
    else:
        st.info("No grades added yet.")

    with st.expander("Add Course Grade"):
        course_code = st.text_input("Course Code", key="grade_course_code")
        course_name = st.text_input("Course Name", key="grade_course_name")
        credits = st.number_input("Credits", min_value=1, max_value=10, value=3)
        grade_letter = st.selectbox("Grade", ["AA", "BA", "BB", "CB", "CC", "DC", "DD", "FD", "FF"])

        if st.button("Add Grade"):
            if not course_code or not course_name:
                st.warning("Please enter course code and course name.")
            else:
                add_grade(st.session_state.username, course_code, course_name, credits, grade_letter)
                st.success("Grade added. GPA updated automatically.")
                st.rerun()

    with st.expander("Delete Grade"):
        if grades:
            grade_options = {
                f"{row[1]} - {row[2]} ({row[4]})": row[0]
                for row in grades
            }

            selected_grade = st.selectbox("Select grade to delete", list(grade_options.keys()))

            if st.button("Delete Selected Grade"):
                delete_grade(grade_options[selected_grade])
                st.success("Grade deleted.")
                st.rerun()

    st.subheader("Notifications")
    st.markdown(f"""
    <div class="box">
        <p>🔔 New academic recommendation is available.</p>
        <p>📌 Attendance is currently <b>{student["attendance"]}</b>.</p>
        <p>⚠️ Risk level is <b>{student["risk_level"]}</b>. Focus on your core courses.</p>
    </div>
    """, unsafe_allow_html=True)


elif page == "💬 Academic Advisor":
    student = load_student_data(st.session_state.username)

    st.markdown('<div class="big-title">Academic Advisor</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="small-text">Ask naturally. Example: "Which course teaches the first programming course?" or "Who knows blockchain?"</div>',
        unsafe_allow_html=True
    )

    question = st.text_input("Ask your question:")
    show_debug = st.checkbox("Show retrieved context", value=False)

    if st.button("Send Question"):
        if not question:
            st.warning("Please write a question first.")
        else:
            with st.spinner("Searching semantic knowledge base and generating answer..."):
                context, retrieval_mode = get_best_context(question, student)
                response = generate_answer_with_azure_first(question, context, student)

                if show_debug:
                    with st.expander("Debug: Retrieved context", expanded=True):
                        st.write("Retrieval mode:", retrieval_mode)
                        st.write("Context found:", bool(context))
                        st.write("Context length:", len(context))
                        st.text_area("Context", context[:MAX_CONTEXT_CHARS], height=250)

            if not response or response.strip() == "":
                st.warning("No result found. Please try another question.")
            else:
                st.success(f"Response generated successfully using {retrieval_mode}.")
                st.session_state.chat_history.append({
                    "question": question,
                    "answer": response,
                    "time": datetime.now().strftime("%Y-%m-%d %H:%M")
                })

    st.subheader("Chat History")

    if st.button("Clear Chat History"):
        st.session_state.chat_history = []
        st.success("Chat history cleared.")
        st.rerun()

    if len(st.session_state.chat_history) == 0:
        st.info("No chat history yet.")
    else:
        for chat in st.session_state.chat_history:
            st.markdown(f"""
            <div class="response-box">
                <b>Question:</b> {chat["question"]}<br><br>
                <b>Answer:</b><br>{chat["answer"]}<br><br>
                <span style="color:#6b7280;">{chat["time"]}</span>
            </div>
            """, unsafe_allow_html=True)


elif page == "📚 Study Assistant":
    st.markdown('<div class="big-title">Study Assistant</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="small-text">Upload documents, ask the semantic course database, or summarize public webpages.</div>',
        unsafe_allow_html=True
    )

    st.subheader("Ask the Semantic Course Database")
    study_question = st.text_input("Ask about a course, career, professor, calendar, or topic:", key="study_question")

    if st.button("Search Semantic Database"):
        if not study_question:
            st.warning("Please write a question first.")
        else:
            context, retrieval_mode = get_best_context(study_question)
            response = generate_answer_with_azure_first(study_question, context)

            st.success(f"Response generated using {retrieval_mode}.")
            st.markdown(f"""
            <div class="response-box">
            <b>Result:</b><br><br>
            {response}
            </div>
            """, unsafe_allow_html=True)

    st.subheader("Web Scraping Study Tool")
    webpage_url = st.text_input("Enter a public webpage URL to extract and summarize:", key="webpage_url")

    if st.button("Scrape and Summarize Webpage"):
        if not webpage_url:
            st.warning("Please enter a webpage URL.")
        else:
            scraped_text, scrape_error = scrape_website_text(webpage_url)

            if scrape_error:
                st.error(scrape_error)
            else:
                st.success("Webpage content extracted successfully.")
                st.text_area("Extracted Webpage Text Preview", scraped_text[:3000], height=250)

                webpage_summary = generate_uploaded_doc_summary_with_azure_first(scraped_text)

                st.markdown(f"""
                <div class="response-box">
                    <h3>Webpage Summary</h3>
                    {webpage_summary}
                </div>
                """, unsafe_allow_html=True)

    st.subheader("Upload Study Document")
    uploaded_file = st.file_uploader("Upload PDF / DOCX / TXT", type=["pdf", "docx", "txt"])

    if uploaded_file:
        st.success("File uploaded successfully.")
        extracted_text = ""

        if uploaded_file.name.endswith(".txt"):
            extracted_text = uploaded_file.read().decode("utf-8", errors="ignore")

        elif uploaded_file.name.endswith(".pdf"):
            if PyPDF2 is None:
                st.error("PyPDF2 is not installed. Run: pip install PyPDF2")
            else:
                try:
                    pdf_reader = PyPDF2.PdfReader(uploaded_file)
                    for page_pdf in pdf_reader.pages:
                        text = page_pdf.extract_text()
                        if text:
                            extracted_text += text + "\n"
                except Exception as e:
                    st.error("Could not read this PDF.")
                    st.code(str(e))

        elif uploaded_file.name.endswith(".docx"):
            if docx2txt is None:
                st.error("docx2txt is not installed. Run: pip install docx2txt")
            else:
                try:
                    with open(uploaded_file.name, "wb") as f:
                        f.write(uploaded_file.getbuffer())
                    extracted_text = docx2txt.process(uploaded_file.name)
                except Exception as e:
                    st.error("Could not read this DOCX file.")
                    st.code(str(e))

        if extracted_text:
            st.subheader("Extracted Text Preview")
            st.text_area("Preview", extracted_text[:3000], height=250)
            st.info(f"Document word count: {len(extracted_text.split())}")

            if st.button("Generate Summary"):
                summary = generate_uploaded_doc_summary_with_azure_first(extracted_text)

                st.markdown(f"""
                <div class="response-box">
                    <h3>Summary</h3>
                    {summary}
                </div>
                """, unsafe_allow_html=True)
        else:
            st.warning("No readable text found.")


elif page == "⚙️ Settings":
    st.markdown('<div class="big-title">Settings</div>', unsafe_allow_html=True)
    st.selectbox("Theme", ["Light", "Dark"])
    st.selectbox("Language", ["English", "Turkish", "French"])
    st.checkbox("Enable Notifications", value=True)

    if st.button("Save Settings"):
        st.success("Settings saved successfully.")


elif page == "🚪 Logout":
    st.markdown('<div class="big-title">Logout</div>', unsafe_allow_html=True)

    if st.button("Confirm Logout"):
        st.session_state.logged_in = False
        st.session_state.username = ""
        st.rerun()


elif page == "🔐 Admin Dashboard":
    st.markdown('<div class="big-title">Admin Dashboard</div>', unsafe_allow_html=True)

    students = get_all_students()

    st.subheader("Students Management")
    st.table([
        {
            "Username": s[0],
            "Name": s[1],
            "Student ID": s[2],
            "Department": s[3],
            "Semester": s[4],
            "Attendance": s[5]
        }
        for s in students
    ])

    with st.expander("Delete Student"):
        usernames = [s[0] for s in students]

        if usernames:
            selected_user = st.selectbox("Select student", usernames)

            if st.button("Delete Student"):
                delete_student(selected_user)
                st.success("Student deleted.")
                st.rerun()

    with st.expander("Add Grade to Any Student"):
        usernames = [s[0] for s in students]

        if usernames:
            selected_student = st.selectbox("Student", usernames, key="admin_grade_student")
            course_code = st.text_input("Course Code", key="admin_course_code")
            course_name = st.text_input("Course Name", key="admin_course_name")
            credits = st.number_input("Credits", min_value=1, max_value=10, value=3, key="admin_credits")
            grade_letter = st.selectbox("Grade", ["AA", "BA", "BB", "CB", "CC", "DC", "DD", "FD", "FF"], key="admin_grade_letter")

            if st.button("Add Grade as Admin"):
                if not course_code or not course_name:
                    st.warning("Please fill course code and course name.")
                else:
                    add_grade(selected_student, course_code, course_name, credits, grade_letter)
                    st.success("Grade added.")
                    st.rerun()

    st.subheader("Semantic RAG Index")

    if build_semantic_index is not None:
        if st.button("Rebuild Semantic Index"):
            with st.spinner("Building FAISS semantic vector index..."):
                build_semantic_index(force_rebuild=True)
            st.success("Semantic FAISS index rebuilt successfully.")
    else:
        st.warning("Semantic RAG module is not available. Check semantic_rag.py and installations.")

    st.subheader("System Information")
    course_database = load_course_database()

    if USE_AZURE_BACKEND:
        provider = "Azure OpenAI + Azure Search"
    elif USE_GROQ_BACKEND:
        provider = "Groq Cloud"
    else:
        provider = "Local document search"

    st.markdown(f"""
    <div class="box">
        <p><b>Current Main AI Provider:</b> {provider}</p>
        <p><b>Retrieval System:</b> Semantic FAISS RAG with keyword fallback</p>
        <p><b>Student Data:</b> Local SQLite database active</p>
        <p><b>Course Database File:</b> {COURSE_DATABASE_FILE}</p>
        <p><b>Course Database Status:</b> {"Loaded" if course_database else "Not found"}</p>
        <p><b>Web Scraping Tool:</b> Enabled</p>
        <p><b>Azure Backend Enabled:</b> {USE_AZURE_BACKEND}</p>
        <p><b>Groq Backend Enabled:</b> {USE_GROQ_BACKEND}</p>
        <p><b>Last Check:</b> {datetime.now().strftime("%Y-%m-%d %H:%M")}</p>
    </div>
    """, unsafe_allow_html=True)