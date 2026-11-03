"""Create/update chemistry.db with official NESA paper references.

Question image BLOBs are imported from the supplied PDFs by buildDatabase.py.
This script only maintains the paper source metadata.
"""

import sqlite3
import os
from pathlib import Path


DB_PATH = Path(os.getenv("CHEMISTRY_DB_PATH", Path(__file__).with_name("chemistry.db")))

PAPERS = [
    (2019, 21, 34, "https://www.nsw.gov.au/education-and-training/nesa/curriculum/hsc-exam-papers/chemistry/2019", "https://www.nsw.gov.au/sites/default/files/noindex/2025-05/2019-hsc-chemistry.pdf", "https://www.nsw.gov.au/sites/default/files/noindex/2025-05/2019-hsc-chemistry-mg.pdf"),
    (2020, 21, 36, "https://www.nsw.gov.au/education-and-training/nesa/curriculum/hsc-exam-papers/chemistry/2020", "https://www.nsw.gov.au/sites/default/files/noindex/2025-05/2020-hsc-chemistry.pdf", "https://www.nsw.gov.au/sites/default/files/noindex/2025-05/2020-hsc-chemistry-mg.pdf"),
    (2021, 21, 36, "https://www.nsw.gov.au/education-and-training/nesa/curriculum/hsc-exam-papers/chemistry/2021", "https://www.nsw.gov.au/sites/default/files/noindex/2025-05/2021-hsc-chemistry.pdf", "https://www.nsw.gov.au/sites/default/files/noindex/2025-05/2021-hsc-chemistry-mg.pdf"),
    (2022, 21, 36, "https://www.nsw.gov.au/education-and-training/nesa/curriculum/hsc-exam-papers/chemistry/2022", "https://www.nsw.gov.au/sites/default/files/noindex/2025-05/2022-hsc-chemistry.pdf", "https://www.nsw.gov.au/sites/default/files/noindex/2025-05/2022-hsc-chemistry-mg.pdf"),
    (2023, 21, 37, "https://www.nsw.gov.au/education-and-training/nesa/curriculum/hsc-exam-papers/chemistry/2023", "https://www.nsw.gov.au/sites/default/files/noindex/2025-05/2023-hsc-chemistry_20240318.pdf", "https://www.nsw.gov.au/sites/default/files/noindex/2025-05/2023-hsc-chemistry-mg.pdf"),
    (2024, 21, 39, "https://www.nsw.gov.au/education-and-training/nesa/curriculum/hsc-exam-papers/chemistry/2024", "https://www.nsw.gov.au/sites/default/files/noindex/2025-05/2024-hsc-chemistry.pdf", "https://www.nsw.gov.au/sites/default/files/noindex/2025-05/2024-hsc-chemistry-mg.pdf"),
    (2025, 21, 37, "https://www.nsw.gov.au/education-and-training/nesa/curriculum/hsc-exam-papers/chemistry/2025", "https://www.nsw.gov.au/sites/default/files/noindex/2025-11/2025-hsc-chemistry.pdf", None),
]

def build_database() -> None:
    with sqlite3.connect(DB_PATH) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS papers (
                year INTEGER PRIMARY KEY,
                source_page_url TEXT NOT NULL,
                pdf_url TEXT NOT NULL,
                marking_pdf_url TEXT,
                first_section_ii_question INTEGER NOT NULL,
                last_section_ii_question INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS questions (
                year INTEGER NOT NULL REFERENCES papers(year),
                reference TEXT NOT NULL,
                question_number INTEGER NOT NULL,
                topic TEXT NOT NULL DEFAULT '',
                pdf_page INTEGER,
                marking_guide_text TEXT,
                pdf_page_end INTEGER,
                marking_guide_pages TEXT,
                source_pdf_url TEXT,
                marking_pdf_url TEXT,
                marks INTEGER,
                module TEXT,
                PRIMARY KEY (year, reference, topic)
            );
            CREATE INDEX IF NOT EXISTS idx_questions_topic
                ON questions(topic, year);
            CREATE TABLE IF NOT EXISTS question_images (
                year INTEGER NOT NULL,
                reference TEXT NOT NULL,
                media_type TEXT NOT NULL,
                width INTEGER NOT NULL,
                height INTEGER NOT NULL,
                page_numbers TEXT NOT NULL,
                image_blob BLOB NOT NULL,
                source_pdf_url TEXT NOT NULL,
                PRIMARY KEY (year, reference)
            );
            CREATE TABLE IF NOT EXISTS mcq_questions (
                year INTEGER NOT NULL,
                question_number INTEGER NOT NULL,
                pdf_page INTEGER NOT NULL,
                correct_option TEXT NOT NULL CHECK (correct_option IN ('A','B','C','D')),
                image_blob BLOB NOT NULL,
                source_pdf_url TEXT NOT NULL,
                PRIMARY KEY (year, question_number)
            );
            """
        )
        for table, old_name, new_name in (
            ("questions", "source_pdf_path", "source_pdf_url"),
            ("questions", "marking_pdf_path", "marking_pdf_url"),
            ("questions", "syllabus_category", "module"),
            ("question_images", "source_pdf_path", "source_pdf_url"),
        ):
            columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
            if old_name in columns and new_name not in columns:
                connection.execute(
                    f"ALTER TABLE {table} RENAME COLUMN {old_name} TO {new_name}"
                )
        paper_columns = {row[1] for row in connection.execute("PRAGMA table_info(papers)")}
        if "marking_pdf_url" not in paper_columns:
            connection.execute("ALTER TABLE papers ADD COLUMN marking_pdf_url TEXT")
        for year, first_question, last_question, page_url, pdf_url, marking_pdf_url in PAPERS:
            connection.execute(
                """INSERT INTO papers
                   (year, source_page_url, pdf_url, first_section_ii_question,
                    last_section_ii_question, marking_pdf_url)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(year) DO UPDATE SET
                     source_page_url=excluded.source_page_url,
                     pdf_url=excluded.pdf_url,
                     marking_pdf_url=excluded.marking_pdf_url,
                     first_section_ii_question=excluded.first_section_ii_question,
                     last_section_ii_question=excluded.last_section_ii_question""",
                (year, page_url, pdf_url, first_question, last_question, marking_pdf_url),
            )


if __name__ == "__main__":
    build_database()
    print(f"Updated {DB_PATH}")
