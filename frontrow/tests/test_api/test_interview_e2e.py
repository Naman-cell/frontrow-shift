import os

os.environ["ENABLE_GEMINI"] = "false"
os.environ["ENABLE_FAST_TRANSCRIPTION"] = "false"

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app


def test_interview_e2e_over_rest_and_websocket() -> None:
    get_settings.cache_clear()
    with TestClient(app) as client:
        create_response = client.post(
            "/api/v1/interviews",
            json={
                "tenant_id": "org_demo",
                "candidate_id": "candidate_demo",
                "duration_minutes": 20,
                "question_mode": "AI",
                "role": {
                    "title": "Python Backend Engineer",
                    "seniority": "mid",
                    "job_description_summary": (
                        "Build FastAPI services, work with PostgreSQL and Redis, "
                        "debug production systems, and deploy AI integrations."
                    ),
                    "resume_summary": (
                        "Candidate has 3 years of backend experience and claims "
                        "FastAPI, Redis, PostgreSQL, and AI model deployment."
                    ),
                    "required_skills": [
                        "Python concurrency",
                        "API design",
                        "PostgreSQL",
                    ],
                },
            },
        )
        assert create_response.status_code == 200
        interview_id = create_response.json()["interview_id"]

        start_response = client.post(f"/api/v1/interviews/{interview_id}/start")
        assert start_response.status_code == 200
        first_payload = start_response.json()
        assert first_payload["query_asked"]
        assert first_payload["completed"] is False

        with client.websocket_connect(f"/api/v1/interviews/{interview_id}/ws") as websocket:
            initial = websocket.receive_json()
            assert initial["query_asked"]

            websocket.send_json(
                {
                    "message_type": "audio_chunk",
                    "audio_stream_id": "stream_test_1",
                    "audio_chunk_base64": "ZmFrZS1hdWRpby0x",
                    "audio_mime_type": "audio/webm",
                }
            )
            websocket.send_json(
                {
                    "message_type": "audio_chunk",
                    "audio_stream_id": "stream_test_1",
                    "audio_chunk_base64": "ZmFrZS1hdWRpby0y",
                    "audio_mime_type": "audio/webm",
                }
            )
            websocket.send_json(
                {
                    "message_type": "answer",
                    "text": "I am not sure, I do not know that Python topic well.",
                    "audio_stream_id": "stream_test_1",
                    "user_leave": False,
                    "overtime": False,
                    "is_complete": False,
                }
            )
            follow_up = websocket.receive_json()
            assert follow_up["completed"] is False
            assert follow_up["query_asked"]
            assert follow_up["meta"]["move_type"] == "scaffold_retry"
            assert follow_up["meta"]["candidate_intent"] == "refusal"

            websocket.send_json(
                {
                    "text": (
                        "For example, I designed a FastAPI service, measured "
                        "latency in production, and handled tradeoffs around "
                        "database queries."
                    ),
                    "user_leave": False,
                    "overtime": False,
                    "is_complete": False,
                }
            )
            second_follow_up = websocket.receive_json()
            assert second_follow_up["completed"] is False
            assert second_follow_up["meta"]["move_type"] in {
                "drill_down",
                "switch_adjacent_topic",
                "time_boxed_coverage",
            }

            websocket.send_json(
                {
                    "text": "",
                    "user_leave": False,
                    "overtime": True,
                    "is_complete": False,
                }
            )
            completed = websocket.receive_json()
            assert completed["completed"] is True

        report_response = client.get(f"/api/v1/interviews/{interview_id}/report")
        assert report_response.status_code == 200
        report = report_response.json()
        assert report["interview_id"] == interview_id
        assert report["overall_score"] >= 0
