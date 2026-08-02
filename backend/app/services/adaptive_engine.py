from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional

import math


@dataclass
class StudentProfile:
    student_id: str
    ability: float = 0.0
    topic_mastery: Dict[str, float] = field(default_factory=dict)
    response_history: List[dict] = field(default_factory=list)
    videos_watched: int = 0


class AdaptiveEngine:
    difficulty_map = {"EASY": -1.0, "MEDIUM": 0.0, "HARD": 1.5}

    def from_dict(self, payload: Optional[dict], student_id: str) -> StudentProfile:
        if not payload:
            return StudentProfile(student_id=student_id)
        return StudentProfile(
            student_id=payload["student_id"],
            ability=float(payload.get("ability", 0.0)),
            topic_mastery=dict(payload.get("topic_mastery", {})),
            response_history=list(payload.get("response_history", [])),
            videos_watched=int(payload.get("videos_watched", 0)),
        )

    def update_after_answer(
        self,
        profile: StudentProfile,
        topic: str,
        difficulty: str,
        is_correct: bool,
        question_id: str,
    ) -> StudentProfile:
        item_difficulty = self.difficulty_map[difficulty]
        probability = 1 / (1 + math.exp(-(profile.ability - item_difficulty)))
        observed = 1.0 if is_correct else 0.0
        profile.ability += 0.3 * (observed - probability)
        profile.ability = max(-3.0, min(3.0, profile.ability))

        old_mastery = profile.topic_mastery.get(topic, 0.5)
        profile.topic_mastery[topic] = max(0.0, min(1.0, old_mastery + 0.15 * (observed - old_mastery)))
        profile.response_history.append(
            {
                "question_id": question_id,
                "topic": topic,
                "difficulty": difficulty,
                "correct": is_correct,
            }
        )
        return profile

    def weak_topics(self, profile: StudentProfile) -> List[str]:
        return [topic for topic, score in profile.topic_mastery.items() if score < 0.45]

    def strong_topics(self, profile: StudentProfile) -> List[str]:
        return [topic for topic, score in profile.topic_mastery.items() if score >= 0.75]

    def next_topic(self, profile: StudentProfile) -> Optional[str]:
        weak = self.weak_topics(profile)
        if weak:
            return sorted(weak, key=lambda topic: profile.topic_mastery[topic])[0]
        return None

    def to_dict(self, profile: StudentProfile) -> dict:
        return asdict(profile)


adaptive_engine = AdaptiveEngine()
