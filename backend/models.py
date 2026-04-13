from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    is_approved = Column(Boolean, default=False)
    is_admin = Column(Boolean, default=False)
    custom_prompt = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    generations = relationship("Generation", back_populates="user")


class Generation(Base):
    __tablename__ = "generations"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    input_text = Column(Text, nullable=False)
    params_json = Column(Text, nullable=True)    # legacy flat format
    ir_json = Column(Text, nullable=True)         # IR tree JSON (new)
    scad_code = Column(Text, nullable=True)
    stl_url = Column(Text, nullable=True)
    status = Column(String, default="pending")    # pending / success / failed
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    parent_id = Column(Integer, ForeignKey("generations.id"), nullable=True)

    user = relationship("User", back_populates="generations")
    parent = relationship("Generation", remote_side=[id])


class SystemPrompt(Base):
    __tablename__ = "system_prompts"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)
    content = Column(Text, nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
