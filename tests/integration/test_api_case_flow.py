from __future__ import annotations

from services.common.models import Case, CaseStatus, Job, JobStatus
from services.worker.app.main import recover_interrupted_jobs


def test_health_endpoints(client):
    for path in ["/", "/health/live", "/health/ready"]:
        response = client.get(path)
        assert response.status_code == 200


def test_create_and_read_case_and_job(client):
    create_response = client.post(
        "/cases",
        json={
            "title": "Cannot login to dashboard",
            "description": "User cannot access the dashboard after a password reset.",
        },
    )
    assert create_response.status_code == 201

    payload = create_response.json()
    case_id = payload["case"]["id"]
    job_id = payload["job"]["id"]

    assert payload["case"]["status"] == "queued"
    assert payload["job"]["status"] == "pending"
    assert payload["job"]["job_type"] == "triage_case"
    assert payload["job"]["case_id"] == case_id

    list_response = client.get("/cases")
    assert list_response.status_code == 200
    assert any(item["id"] == case_id for item in list_response.json())

    case_response = client.get(f"/cases/{case_id}")
    assert case_response.status_code == 200
    assert case_response.json()["title"] == "Cannot login to dashboard"

    job_response = client.get(f"/jobs/{job_id}")
    assert job_response.status_code == 200
    assert job_response.json()["case_id"] == case_id


def test_read_jobs_for_case(client):
    create_response = client.post(
        "/cases",
        json={
            "title": "Billing charge question",
            "description": "User asks about an unexpected invoice charge.",
        },
    )
    assert create_response.status_code == 201

    payload = create_response.json()
    case_id = payload["case"]["id"]
    job_id = payload["job"]["id"]

    jobs_response = client.get(f"/cases/{case_id}/jobs")
    assert jobs_response.status_code == 200
    jobs = jobs_response.json()
    assert len(jobs) == 1
    assert jobs[0]["id"] == job_id
    assert jobs[0]["case_id"] == case_id

    missing_response = client.get("/cases/does-not-exist/jobs")
    assert missing_response.status_code == 404


def test_starter_worker_requeues_interrupted_jobs(client, db_session):
    interrupted_response = client.post(
        "/cases",
        json={
            "title": "Interrupted case",
            "description": "The worker stopped while processing this case.",
        },
    )
    completed_response = client.post(
        "/cases",
        json={
            "title": "Completed case",
            "description": "This case was already processed.",
        },
    )
    interrupted = interrupted_response.json()
    completed = completed_response.json()

    interrupted_job = db_session.get(Job, interrupted["job"]["id"])
    completed_job = db_session.get(Job, completed["job"]["id"])
    assert interrupted_job is not None
    assert completed_job is not None
    interrupted_job.status = JobStatus.CLAIMED.value
    interrupted_job.error = "stale error"
    completed_job.status = JobStatus.COMPLETED.value
    interrupted_case = db_session.get(Case, interrupted["case"]["id"])
    assert interrupted_case is not None
    interrupted_case.status = CaseStatus.FAILED.value
    db_session.commit()

    assert recover_interrupted_jobs(db_session) == 1

    db_session.refresh(interrupted_job)
    db_session.refresh(completed_job)
    assert interrupted_job.status == JobStatus.PENDING.value
    assert interrupted_job.claimed_at is None
    assert interrupted_job.error is None
    db_session.refresh(interrupted_case)
    assert interrupted_case.status == CaseStatus.QUEUED.value
    assert completed_job.status == JobStatus.COMPLETED.value
