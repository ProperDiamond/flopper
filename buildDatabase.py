"""Extract supplied HSC Chemistry papers and marking guides into chemistry.db.

Question wording comes from user-supplied PDFs. The NESA paper remains the
authoritative visual source for diagrams and structural formulae.
"""

from __future__ import annotations

import io
import re
import sqlite3
import os
import sys
from pathlib import Path

import pdfplumber
from PIL import Image


PDF_DIRECTORY = Path(__file__).resolve().parent / "papers"
DB_PATH = Path(os.getenv("CHEMISTRY_DB_PATH", Path(__file__).with_name("chemistry.db")))
PDFS = {
    2019: ("2019-hsc-chemistry.pdf", "2019-hsc-chemistry-mg.pdf"),
    2020: ("2020-hsc-chemistry.pdf", "2020-hsc-chemistry-mg.pdf"),
    2021: ("2021-hsc-chemistry.pdf", "2021-hsc-chemistry-mg.pdf"),
    2022: ("2022-hsc-chemistry.pdf", "2022-hsc-chemistry-mg.pdf"),
    2023: ("2023-hsc-chemistry_20240318.pdf", "2023-hsc-chemistry-mg.pdf"),
    2024: ("2024-hsc-chemistry.pdf", "2024-hsc-chemistry-mg.pdf"),
}

QUESTION_HEADER = re.compile(r"^\s*Question\s+(\d{1,2})\b(.*)$", re.IGNORECASE)
MCQ_HEADER = re.compile(r"^\s*(\d{1,2})(?!\d)\s+\S")
MARK_HEADER = re.compile(
    r"^\s*Question\s+(\d{1,2})(?:\s*\(([a-z])\))?\s*$", re.IGNORECASE
)
END_OF_QUESTIONS = re.compile(
    r"^\s*(?:Formulae Sheet|Data Sheet|Periodic Table|Multiple Choice Answer Sheet)\b",
    re.IGNORECASE,
)

# Primary module and syllabus topic for each whole HSC question. These labels
# apply to the 2019–2024 Chemistry Stage 6 papers in this database.
SYLLABUS_MODULES = {
    "m2_gas": "Module 2: Introduction to Quantitative Chemistry",
    "m4_energy": "Module 4: Drivers of Reactions",
    "m4_entropy": "Module 4: Drivers of Reactions",
    "m5_dynamic": "Module 5: Equilibrium and Acid Reactions",
    "m5_factors": "Module 5: Equilibrium and Acid Reactions",
    "m5_keq": "Module 5: Equilibrium and Acid Reactions",
    "m5_solubility": "Module 5: Equilibrium and Acid Reactions",
    "m6_properties": "Module 6: Acid/base Reactions",
    "m6_water": "Module 6: Acid/base Reactions",
    "m6_quant": "Module 6: Acid/base Reactions",
    "m7_nomenclature": "Module 7: Organic Chemistry",
    "m7_hydrocarbons": "Module 7: Organic Chemistry",
    "m7_alcohols": "Module 7: Organic Chemistry",
    "m7_organic_acids": "Module 7: Organic Chemistry",
    "m7_polymers": "Module 7: Organic Chemistry",
    "m8_inorganic": "Module 8: Applying Chemical Ideas",
    "m8_organic": "Module 8: Applying Chemical Ideas",
    "m8_synthesis": "Module 8: Applying Chemical Ideas",
}

SYLLABUS_TOPICS = {
    "m2_gas": "Gas Laws",
    "m4_energy": "Energy Changes in Chemical Reactions",
    "m4_entropy": "Entropy and Gibbs Free Energy",
    "m5_dynamic": "Static and Dynamic Equilibrium",
    "m5_factors": "Factors that Affect Equilibrium",
    "m5_keq": "Calculating the Equilibrium Constant",
    "m5_solubility": "Solution Equilibria",
    "m6_properties": "Properties of Acids and Bases",
    "m6_water": "Using Brønsted–Lowry Theory",
    "m6_quant": "Quantitative Analysis",
    "m7_nomenclature": "Nomenclature",
    "m7_hydrocarbons": "Products of Reactions Involving Hydrocarbons",
    "m7_alcohols": "Alcohols",
    "m7_organic_acids": "Reactions of Organic Acids and Bases",
    "m7_polymers": "Polymers",
    "m8_inorganic": "Analysis of Inorganic Substances",
    "m8_organic": "Analysis of Organic Substances",
    "m8_synthesis": "Chemical Synthesis and Design",
}

QUESTION_SYLLABUS = {
    2019: {21:"m7_nomenclature",22:"m6_water",23:"m4_energy",24:"m6_quant",25:"m5_factors",26:"m8_organic",27:"m6_water",28:"m6_properties",29:"m5_solubility",30:"m5_solubility",31:"m5_keq",32:"m7_alcohols",33:"m6_quant",34:"m8_synthesis"},
    2020: {21:"m8_organic",22:"m8_inorganic",23:"m8_synthesis",24:"m8_synthesis",25:"m6_quant",26:"m4_energy",27:"m6_water",28:"m6_quant",29:"m7_hydrocarbons",30:"m8_organic",31:"m8_inorganic",32:"m7_organic_acids",33:"m6_quant",34:"m6_water",35:"m5_keq",36:"m4_energy"},
    2021: {21:"m7_hydrocarbons",22:"m5_factors",23:"m6_properties",24:"m7_nomenclature",25:"m2_gas",26:"m7_hydrocarbons",27:"m5_solubility",28:"m8_inorganic",29:"m8_organic",30:"m8_inorganic",31:"m5_keq",32:"m6_properties",33:"m4_entropy",34:"m6_water",35:"m8_organic",36:"m6_water"},
    2022: {21:"m7_hydrocarbons",22:"m6_properties",23:"m5_factors",24:"m7_hydrocarbons",25:"m6_water",26:"m4_energy",27:"m7_alcohols",28:"m8_inorganic",29:"m4_energy",30:"m8_organic",31:"m8_inorganic",32:"m6_quant",33:"m8_synthesis",34:"m6_water",35:"m5_solubility",36:"m5_dynamic"},
    2023: {21:"m7_nomenclature",22:"m6_properties",23:"m6_water",24:"m6_water",25:"m4_energy",26:"m5_factors",27:"m2_gas",28:"m7_hydrocarbons",29:"m7_alcohols",30:"m8_inorganic",31:"m8_inorganic",32:"m8_inorganic",33:"m5_factors",34:"m5_solubility",35:"m6_water",36:"m8_organic",37:"m5_keq"},
    2024: {21:"m6_properties",22:"m7_polymers",23:"m5_factors",24:"m7_organic_acids",25:"m8_inorganic",26:"m5_dynamic",27:"m8_inorganic",28:"m6_water",29:"m6_quant",30:"m5_keq",31:"m8_synthesis",32:"m5_solubility",33:"m8_organic",34:"m6_quant",35:"m8_organic",36:"m4_energy",37:"m5_keq",38:"m7_hydrocarbons",39:"m5_solubility"},
}


def page_lines(pdf_path: Path) -> list[tuple[int, str]]:
    output: list[tuple[int, str]] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            text = page.extract_text(layout=False) or ""
            for line in text.splitlines():
                output.append((page_number, line.rstrip()))
    return output


def extract_questions(pdf_path: Path) -> dict[int, dict[str, object]]:
    extracted: dict[int, dict[str, object]] = {}
    current: dict[str, object] | None = None

    def finish() -> None:
        if current is None:
            return
        extracted[int(current["number"])] = current.copy()

    for page_number, line in page_lines(pdf_path):
        if current is not None and END_OF_QUESTIONS.match(line):
            finish()
            current = None
            continue
        match = QUESTION_HEADER.match(line)
        if match and int(match.group(1)) >= 21:
            number = int(match.group(1))
            if current is not None and number == current["number"]:
                current["end_page"] = page_number
            else:
                finish()
                mark_match = re.search(r"\((\d+)\s+marks?\)", match.group(2), re.IGNORECASE)
                current = {
                    "number": number,
                    "start_page": page_number,
                    "end_page": page_number,
                    "marks": int(mark_match.group(1)) if mark_match else None,
                }
        elif current is not None:
            current["end_page"] = page_number

    finish()
    return extracted


def extract_marking_guides(pdf_path: Path) -> dict[int, dict[str, object]]:
    by_question: dict[int, dict[str, object]] = {}
    current_number: int | None = None

    for page_number, line in page_lines(pdf_path):
        match = MARK_HEADER.match(line)
        if match:
            current_number = int(match.group(1))
            record = by_question.setdefault(
                current_number, {"pages": set(), "lines": []}
            )
            record["pages"].add(page_number)
            record["lines"].append(line.strip())
        elif current_number is not None:
            record = by_question[current_number]
            record["pages"].add(page_number)
            record["lines"].append(line.strip())

    for record in by_question.values():
        record["text"] = "\n".join(record.pop("lines")).strip()
        record["pages"] = sorted(record["pages"])
    return by_question


def ensure_schema(connection: sqlite3.Connection) -> None:
    columns = {
        row[1] for row in connection.execute("PRAGMA table_info(questions)")
    }
    for old_name, new_name in (
        ("source_pdf_path", "source_pdf_url"),
        ("marking_pdf_path", "marking_pdf_url"),
        ("syllabus_category", "module"),
    ):
        if old_name in columns and new_name not in columns:
            connection.execute(
                f"ALTER TABLE questions RENAME COLUMN {old_name} TO {new_name}"
            )
            columns.remove(old_name)
            columns.add(new_name)
    additions = {
        "marking_guide_text": "TEXT",
        "pdf_page_end": "INTEGER",
        "marking_guide_pages": "TEXT",
        "source_pdf_url": "TEXT",
        "marking_pdf_url": "TEXT",
        "marks": "INTEGER",
        "module": "TEXT",
    }
    for column, data_type in additions.items():
        if column not in columns:
            connection.execute(
                f"ALTER TABLE questions ADD COLUMN {column} {data_type}"
            )
    for year, reference in connection.execute(
        "SELECT year, reference FROM questions "
        "WHERE topic IS NULL OR trim(topic) = ''"
    ).fetchall():
        topic = topic_for_question(year, reference)
        if topic:
            connection.execute(
                "UPDATE questions SET topic = ? WHERE year = ? AND reference = ? "
                "AND (topic IS NULL OR trim(topic) = '')",
                (topic, year, reference),
            )
    connection.execute("DROP TABLE IF EXISTS question_images")
    connection.execute(
        """CREATE TABLE question_images (
             year INTEGER NOT NULL,
             reference TEXT NOT NULL,
             media_type TEXT NOT NULL,
             width INTEGER NOT NULL,
             height INTEGER NOT NULL,
             page_numbers TEXT NOT NULL,
             image_blob BLOB NOT NULL,
             source_pdf_url TEXT NOT NULL,
             PRIMARY KEY (year, reference)
           )"""
    )
    ensure_mcq_schema(connection)


def topic_for_question(year: int, reference: str) -> str:
    """Return the syllabus topic associated with a short-answer question."""
    match = re.fullmatch(r"Q(\d+)", reference)
    if not match:
        return ""
    topic_key = QUESTION_SYLLABUS.get(year, {}).get(int(match.group(1)))
    return SYLLABUS_TOPICS.get(topic_key, "")


def question_image(pdf: pdfplumber.PDF, question: dict[str, object]) -> tuple[bytes, int, int, str]:
    """Render the question's page sections and join them into one PNG image."""
    number = int(question["number"])
    start_page = int(question["start_page"])
    end_page = int(question["end_page"])
    crops: list[Image.Image] = []
    page_numbers: list[int] = []
    resolution = 120

    for page_number in range(start_page, end_page + 1):
        page = pdf.pages[page_number - 1]
        lines = page.extract_text_lines() or []
        headers: list[tuple[int, float]] = []
        for line in lines:
            match = re.match(r"^\s*Question\s+(\d{1,2})\b", line["text"], re.I)
            if match:
                headers.append((int(match.group(1)), float(line["top"])))

        own_headers = [top for header_number, top in headers if header_number == number]
        # Each continuation page has its own continued-question heading. If
        # extraction misses one, start below the paper's top margin.
        top_pt = (min(own_headers) - 7) if own_headers else 48.0
        later_headers = [
            top for header_number, top in headers
            if header_number != number and top > top_pt + 8
        ]
        bottom_pt = min(later_headers) - 5 if later_headers else float(page.height) - 30
        top_pt = max(0.0, top_pt)
        bottom_pt = min(float(page.height), max(top_pt + 40, bottom_pt))

        rendered = page.to_image(resolution=resolution).original
        scale = resolution / 72
        crop_box = (
            0,
            max(0, int(top_pt * scale)),
            rendered.width,
            min(rendered.height, int(bottom_pt * scale)),
        )
        crops.append(rendered.crop(crop_box).convert("RGB"))
        page_numbers.append(page_number)

    width = max(crop.width for crop in crops)
    height = sum(crop.height for crop in crops)
    combined = Image.new("RGB", (width, height), "white")
    offset = 0
    for crop in crops:
        combined.paste(crop, (0, offset))
        offset += crop.height
    output = io.BytesIO()
    combined.save(output, format="PNG", optimize=True)
    return output.getvalue(), width, height, ",".join(map(str, page_numbers))


def ensure_mcq_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """CREATE TABLE IF NOT EXISTS mcq_questions (
             year INTEGER NOT NULL,
             question_number INTEGER NOT NULL,
             pdf_page INTEGER NOT NULL,
             correct_option TEXT NOT NULL CHECK (correct_option IN ('A','B','C','D')),
             image_blob BLOB NOT NULL,
             source_pdf_url TEXT NOT NULL,
             PRIMARY KEY (year, question_number)
           )"""
    )


def extract_mcq_headers(pdf: pdfplumber.PDF) -> list[tuple[int, int, float]]:
    """Find the 20 numbered question starts, returning number/page/top."""
    headers: list[tuple[int, int, float]] = []
    expected_number = 1
    for page_index, page in enumerate(pdf.pages):
        for line in page.extract_text_lines() or []:
            if float(line["x0"]) > 90:
                continue
            match = MCQ_HEADER.match(line["text"])
            if not match or int(match.group(1)) != expected_number:
                continue
            headers.append((expected_number, page_index, float(line["top"])))
            expected_number += 1
            if expected_number == 21:
                return headers
    raise ValueError(f"Found {len(headers)} of the 20 Section I question starts.")


def extract_mcq_answers(guide_path: Path) -> dict[int, str]:
    with pdfplumber.open(guide_path) as pdf:
        text = pdf.pages[0].extract_text() or ""
    answers: dict[int, str] = {}
    for line in text.splitlines():
        match = re.match(r"^\s*(\d{1,2})\s+([A-D])\s*$", line)
        if match:
            answers[int(match.group(1))] = match.group(2)
    if set(answers) != set(range(1, 21)):
        raise ValueError(f"Could not read the full MCQ answer key in {guide_path.name}.")
    return answers


def render_mcq_image(
    pdf: pdfplumber.PDF,
    current: tuple[int, int, float],
    following: tuple[int, int, float] | None,
) -> bytes:
    """Render one MCQ, including all continuation pages up to the next item."""
    _, start_index, start_top = current
    end_index = following[1] if following else start_index
    crops: list[Image.Image] = []
    resolution = 120
    scale = resolution / 72

    for page_index in range(start_index, end_index + 1):
        page = pdf.pages[page_index]
        top_pt = max(0.0, start_top - 7) if page_index == start_index else 38.0
        if following and page_index == end_index:
            bottom_pt = max(top_pt + 5, following[2] - 5)
        else:
            bottom_pt = float(page.height) - 28

        rendered = page.to_image(resolution=resolution).original
        crop_box = (
            0,
            max(0, int(top_pt * scale)),
            rendered.width,
            min(rendered.height, int(bottom_pt * scale)),
        )
        crops.append(rendered.crop(crop_box).convert("RGB"))

    width = max(crop.width for crop in crops)
    height = sum(crop.height for crop in crops)
    combined = Image.new("RGB", (width, height), "white")
    offset = 0
    for crop in crops:
        combined.paste(crop, (0, offset))
        offset += crop.height
    output = io.BytesIO()
    combined.save(output, format="PNG", optimize=True)
    return output.getvalue()


def import_mcq_year(connection: sqlite3.Connection, year: int, paper_name: str, guide_name: str) -> int:
    paper_path = PDF_DIRECTORY / paper_name
    guide_path = PDF_DIRECTORY / guide_name
    public_paper = connection.execute(
        "SELECT pdf_url FROM papers WHERE year = ?", (year,)
    ).fetchone()
    if public_paper is None:
        raise ValueError(f"No public NESA paper URL is recorded for {year}.")
    answers = extract_mcq_answers(guide_path)
    imported = 0
    with pdfplumber.open(paper_path) as pdf:
        headers = extract_mcq_headers(pdf)
        for index, current in enumerate(headers):
            question_number, page_index, _top = current
            next_header = headers[index + 1] if index + 1 < len(headers) else None
            image_blob = render_mcq_image(pdf, current, next_header)
            connection.execute(
                """INSERT INTO mcq_questions
                   (year, question_number, pdf_page, correct_option, image_blob,
                    source_pdf_url)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(year, question_number) DO UPDATE SET
                     pdf_page=excluded.pdf_page,
                     correct_option=excluded.correct_option,
                     image_blob=excluded.image_blob,
                     source_pdf_url=excluded.source_pdf_url""",
                (
                    year,
                    question_number,
                    page_index + 1,
                    answers[question_number],
                    image_blob,
                    public_paper[0],
                ),
            )
            imported += 1
    return imported


def import_all_mcq_questions() -> None:
    with sqlite3.connect(DB_PATH) as connection:
        ensure_mcq_schema(connection)
        total = 0
        for year, (paper_name, guide_name) in PDFS.items():
            count = import_mcq_year(connection, year, paper_name, guide_name)
            total += count
            print(f"{year}: imported {count} MCQs")
        print(f"Imported {total} MCQs into {DB_PATH}")


def import_year(connection: sqlite3.Connection, year: int, paper_name: str, guide_name: str) -> int:
    paper_path = PDF_DIRECTORY / paper_name
    guide_path = PDF_DIRECTORY / guide_name
    if not paper_path.is_file():
        raise FileNotFoundError(paper_path)
    if not guide_path.is_file():
        raise FileNotFoundError(guide_path)

    paper_record = connection.execute(
        "SELECT pdf_url, marking_pdf_url FROM papers WHERE year = ?", (year,)
    ).fetchone()
    if paper_record is None:
        raise ValueError(
            f"No public NESA paper URL is recorded for {year}; run build_chemistry_db.py first."
        )
    public_paper_url, public_marking_url = paper_record

    question_data = extract_questions(paper_path)
    guide_data = extract_marking_guides(guide_path)
    imported = 0
    with pdfplumber.open(paper_path) as pdf:
        for number, question in question_data.items():
            reference = f"Q{number}"
            guide = guide_data.get(number, {})
            topic_key = QUESTION_SYLLABUS[year][number]
            module_label = SYLLABUS_MODULES[topic_key]
            topic = SYLLABUS_TOPICS[topic_key]
            image_blob, width, height, page_numbers = question_image(pdf, question)
            connection.execute(
            """INSERT INTO questions
               (year, reference, question_number, topic, pdf_page,
                marking_guide_text, pdf_page_end, marking_guide_pages,
                source_pdf_url, marking_pdf_url, marks, module)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(year, reference, topic) DO UPDATE SET
                 pdf_page=excluded.pdf_page,
                 marking_guide_text=excluded.marking_guide_text,
                 pdf_page_end=excluded.pdf_page_end,
                 marking_guide_pages=excluded.marking_guide_pages,
                 source_pdf_url=excluded.source_pdf_url,
                 marking_pdf_url=excluded.marking_pdf_url,
                 marks=excluded.marks,
                 module=excluded.module""",
                (
                    year,
                    reference,
                    number,
                    topic,
                    question["start_page"],
                    guide.get("text"),
                    question["end_page"],
                    ",".join(str(page) for page in guide.get("pages", [])),
                    public_paper_url,
                    public_marking_url,
                    question["marks"],
                    module_label,
                ),
            )
            connection.execute(
                """INSERT INTO question_images
                   (year, reference, media_type, width, height, page_numbers,
                    image_blob, source_pdf_url)
                   VALUES (?, ?, 'image/png', ?, ?, ?, ?, ?)""",
                (year, reference, width, height, page_numbers, image_blob, public_paper_url),
            )
            imported += 1

    return imported


def main() -> None:
    with sqlite3.connect(DB_PATH) as connection:
        ensure_schema(connection)
        total = 0
        for year, (paper_name, guide_name) in PDFS.items():
            count = import_year(connection, year, paper_name, guide_name)
            total += count
            print(f"{year}: imported {count} questions")
        mcq_total = 0
        for year, (paper_name, guide_name) in PDFS.items():
            count = import_mcq_year(connection, year, paper_name, guide_name)
            mcq_total += count
            print(f"{year}: imported {count} MCQs")
        apply_question_categories(connection)
        connection.execute(
            """DELETE FROM questions
               WHERE NOT EXISTS (
                 SELECT 1 FROM question_images AS i
                 WHERE i.year = questions.year AND i.reference = questions.reference
               )"""
        )
        print(
            f"Imported {total} short-answer questions and {mcq_total} MCQs "
            f"into {DB_PATH}"
        )


def apply_question_categories(connection: sqlite3.Connection) -> None:
    expected = {
        (year, f"Q{number}")
        for year, mapping in QUESTION_SYLLABUS.items()
        for number in mapping
    }
    existing = set(connection.execute("SELECT year, reference FROM questions"))
    if existing != expected:
        missing = sorted(expected - existing)
        unexpected = sorted(existing - expected)
        raise ValueError(
            f"Question/category map mismatch. Missing: {missing}; unexpected: {unexpected}"
        )
    connection.executemany(
        "UPDATE questions SET module = ?, topic = ? "
        "WHERE year = ? AND reference = ?",
        [
            (
                SYLLABUS_MODULES[key],
                SYLLABUS_TOPICS[key],
                year,
                f"Q{number}",
            )
            for year, mapping in QUESTION_SYLLABUS.items()
            for number, key in mapping.items()
        ],
    )


if __name__ == "__main__":
    if sys.argv[1:] == ["--mcq-only"]:
        import_all_mcq_questions()
    else:
        main()
