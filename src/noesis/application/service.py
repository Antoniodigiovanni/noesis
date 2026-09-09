from __future__ import annotations

from noesis.application.capture import CaptureService
from noesis.application.learning import LearningService
from noesis.application.queries import QueryService
from noesis.application.reviews import ReviewService
from noesis.persistence.database import Database


class Noesis:
    def __init__(self, database_path=None) -> None:
        self.db = Database(database_path)
        self.db.create_schema()
        self.capture = CaptureService(self.db)
        self.reviews = ReviewService(self.db)
        self.learning = LearningService(self.db, self.reviews.scheduler)
        self.queries = QueryService(self.db)

