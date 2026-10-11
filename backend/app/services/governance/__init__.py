"""Governance platform services: inspections, SLA, audit chain, risk, geofence.

This package aggregates the Smart Governance & Compliance service layer.
Each module is additive: nothing here modifies the existing PPE/live-detection
path (app.services.camera_pipeline / ppe_policy / yolo_detection).
"""
