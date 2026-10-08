"""Versioned synthetic data. No production reset or default reusable passwords."""

import json
import secrets
from importlib.resources import files
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from modam.knowledge import add_edge, ingest_document, save_ontology
from modam.llm import ModelError
from modam.models import DatasetSeed, Document, GraphNode, Role, Stock, User
from modam.schemas import DocumentCreate, GroundedAnswer, Intent, OntologyDefinition
from modam.security import hash_password

SAMPLE_PATH = Path(__file__).resolve().parents[2] / "samples" / "warehouse_poc.json"


def load_dataset() -> dict[str, Any]:
    source = (
        SAMPLE_PATH if SAMPLE_PATH.exists() else files("modam").joinpath("data/warehouse_poc.json")
    )
    return dict(json.loads(source.read_text(encoding="utf-8")))


def seed_sample(db: Session) -> dict[str, str]:
    dataset = load_dataset()
    if db.get(DatasetSeed, dataset["version"]):
        return {}
    # Abort on name collisions instead of replacing roles, users or their passwords.
    for row in dataset["users"]:
        if db.scalar(select(User.id).where(User.username == row["username"])):
            raise ValueError("Sample username collision; use a fresh isolated database")
    for row in dataset["roles"]:
        if db.scalar(select(Role.id).where(Role.name == row["name"])):
            raise ValueError("Sample role collision; use a fresh isolated database")
    save_ontology(db, OntologyDefinition.model_validate(dataset["ontology"]))
    for node in dataset["nodes"]:
        if db.get(GraphNode, node["id"]):
            raise ValueError("Sample graph collision; use a fresh isolated database")
        db.add(
            GraphNode(
                **node,
                ontology_id=dataset["ontology"]["id"],
                source=f"synthetic:{dataset['version']}/{node['id']}",
            )
        )
    db.flush()
    for edge in dataset["edges"]:
        add_edge(db, edge["source"], edge["target"], edge["kind"])
    db.add(Stock(**dataset["stock"]))
    for document in dataset["documents"]:
        if db.get(Document, document["id"]):
            raise ValueError("Sample document collision; use a fresh isolated database")
        ingest_document(db, DocumentCreate.model_validate(document))
    roles = {}
    for row in dataset["roles"]:
        role = Role(**row)
        db.add(role)
        db.flush()
        roles[role.name] = role
    credentials = {}
    for row in dataset["users"]:
        password = secrets.token_urlsafe(24)
        credentials[row["username"]] = password
        db.add(
            User(
                username=row["username"],
                password_hash=hash_password(password),
                roles=[roles[row["role"]]],
            )
        )
    db.add(DatasetSeed(id=dataset["version"]))
    db.commit()
    return credentials


class RecordedInterpreter:
    """Finite fixture adapter, deliberately not an LLM or general language parser."""

    provider = "recorded-fixture"
    model = "warehouse-poc-v1"

    def __init__(self) -> None:
        self.dataset = load_dataset()

    def interpret(self, message: str, history: list[str]) -> Intent:
        row = self.dataset["interpretations"].get(message)
        if row is None:
            raise ModelError("fixture_question_unknown")
        return Intent.model_validate(row)

    def answer(self, question: str, contexts: list[dict[str, Any]]) -> GroundedAnswer:
        return GroundedAnswer(
            answer="\n".join(row["text"] for row in contexts),
            citation_ids=[row["chunk_id"] for row in contexts],
        )
