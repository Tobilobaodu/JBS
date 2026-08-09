"""Pydantic schemas for cover letter workflow — matching 05-openapi.yaml."""

from datetime import datetime
from pydantic import BaseModel, Field


class StartWorkflowRequest(BaseModel):
    cvId: str
    jobPostId: str
    matchId: str | None = None

    model_config = {"populate_by_name": True}


class CoverLetterWorkflowResponse(BaseModel):
    id: str
    cvId: str = Field(alias="cvId")
    jobPostId: str = Field(alias="jobPostId")
    matchId: str | None = Field(None, alias="matchId")
    currentStep: int = Field(alias="current_step")
    status: str
    questionSetVersion: int = Field(alias="question_set_version")
    createdAt: datetime = Field(alias="created_at")

    model_config = {"from_attributes": True, "populate_by_name": True}


class CoverLetterQuestionResponse(BaseModel):
    id: str
    stepNumber: int = Field(alias="step_number")
    questionText: str = Field(alias="question_text")
    questionCategory: str = Field(alias="question_category")

    model_config = {"from_attributes": True, "populate_by_name": True}


class AnswerItem(BaseModel):
    questionId: str
    answerText: str


class SubmitAnswersRequest(BaseModel):
    answers: list[AnswerItem]


class CoverLetterDraftResponse(BaseModel):
    id: str
    workflowId: str = Field(alias="workflow_id")
    versionNumber: int = Field(alias="version_number")
    status: str
    bodyText: str = Field(alias="body_text")
    evidenceReferences: list[str] | None = Field(None, alias="evidence_references")
    promptVersion: str | None = Field(None, alias="prompt_version")
    modelId: str | None = Field(None, alias="model_id")
    createdAt: str = Field(alias="created_at")
    approvedAt: str | None = Field(None, alias="approved_at")

    model_config = {"from_attributes": True, "populate_by_name": True}