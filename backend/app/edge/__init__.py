"""The edge box (APP_ROLE=edge): runs at the client's site next to the
cameras. Holds the face templates, face photos and policy documents; sends
only recognition results (ids, times, scores) to the cloud. Start with:

    uvicorn app.edge.main:app --host 0.0.0.0 --port 8000
"""
