from sqlalchemy.orm import Session


def index_document(session: Session, entity_type: str, entity_id: str, learner_id: str, title: str, body: str, provenance: str) -> None:
    session.connection().exec_driver_sql(
        "DELETE FROM learning_fts WHERE entity_type = ? AND entity_id = ?",
        (entity_type, entity_id),
    )
    session.connection().exec_driver_sql(
        "INSERT INTO learning_fts(entity_type, entity_id, learner_id, title, body, provenance) VALUES (?, ?, ?, ?, ?, ?)",
        (entity_type, entity_id, learner_id, title, body, provenance),
    )

