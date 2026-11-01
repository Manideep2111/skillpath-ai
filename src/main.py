"""FastAPI Application Entry Point for SkillPath AI.

Configures application metadata, CORS middleware, API v1 routes,
health checks, and exception handlers.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.core.config import settings
from src.api.v1.recommendations import router as recommendations_router
from src.api.v1.health import router as health_router
from src.api.v1.evaluation import router as evaluation_router
from src.api.v1.anomalies import router as anomalies_router

app = FastAPI(
    title=settings.app_name,
    description=(
        "SkillPath AI adaptive learning recommendation engine API. "
        "Provides point-in-time skill mastery estimation and deterministic, "
        "explainable recommendation generation."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# CORS Middleware configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount health check routes: both at root /health and /api/v1/health
app.include_router(health_router, tags=["Health"])
app.include_router(health_router, prefix="/api/v1", tags=["Health"])

# Mount recommendations API v1 routes
app.include_router(recommendations_router, prefix="/api/v1", tags=["Recommendations"])

# Mount evaluation and anomalies API v1 routes
app.include_router(evaluation_router, prefix="/api/v1", tags=["Evaluation"])
app.include_router(anomalies_router, prefix="/api/v1", tags=["Anomalies"])


@app.get("/", include_in_schema=False)
def root_info():
    """Root info endpoint providing basic API links."""
    return {
        "app_name": settings.app_name,
        "version": "1.0.0",
        "documentation": "/docs",
        "health": "/health",
        "recommendations_endpoint": "/api/v1/learners/{learner_id}/recommendations",
    }
