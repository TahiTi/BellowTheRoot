from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, UniqueConstraint, Boolean, Index
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime, timezone

Base = declarative_base()


class Project(Base):
    __tablename__ = 'projects'
    __table_args__ = (
        Index('idx_project_created_at', 'created_at'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), unique=True, nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationship to scans
    scans = relationship("Scan", back_populates="project", cascade="all, delete-orphan")

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'scan_count': len(self.scans)
        }


class Scan(Base):
    __tablename__ = 'scans'
    __table_args__ = (
        Index('idx_scan_project_id', 'project_id'),
        Index('idx_scan_target_domain', 'target_domain'),
        Index('idx_scan_status', 'status'),
        Index('idx_scan_started_at', 'started_at'),
        Index('idx_scan_completed_at', 'completed_at'),
        Index('idx_scan_project_target', 'project_id', 'target_domain'),
        Index('idx_scan_target_status', 'target_domain', 'status'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey('projects.id'), nullable=False)
    target_domain = Column(String(255), nullable=False)
    status = Column(String(50), default='pending', nullable=False)  # pending, running, completed, failed
    started_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    completed_at = Column(DateTime, nullable=True)
    subdomain_count = Column(Integer, default=0, nullable=False)
    
    # Progress tracking
    current_tool = Column(String(50), nullable=True)  # Currently running tool
    total_tools = Column(Integer, default=0, nullable=False)  # Total number of enabled tools
    completed_tools = Column(Integer, default=0, nullable=False)  # Number of completed tools

    # Relationships
    project = relationship("Project", back_populates="scans")
    scan_subdomains = relationship("ScanSubdomain", back_populates="scan", cascade="all, delete-orphan")

    def to_dict(self):
        return {
            'id': self.id,
            'project_id': self.project_id,
            'target_domain': self.target_domain,
            'status': self.status,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'subdomain_count': self.subdomain_count,
            'current_tool': self.current_tool,
            'total_tools': self.total_tools,
            'completed_tools': self.completed_tools
        }


class Subdomain(Base):
    __tablename__ = 'subdomains'
    __table_args__ = (
        UniqueConstraint('subdomain', name='unique_subdomain'),
        Index('idx_subdomain_target', 'target_domain'),
        Index('idx_subdomain_last_seen', 'last_seen_at'),
        Index('idx_subdomain_first_seen', 'first_seen_at'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    subdomain = Column(String(255), nullable=False, unique=True, index=True)
    target_domain = Column(String(255), nullable=False)
    first_seen_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    last_seen_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    
    # Additional details (similar to PrettyRecon)
    size = Column(Integer, nullable=True)  # Response size in bytes
    status_code = Column(Integer, nullable=True)
    headers = Column(Text, nullable=True)  # JSON string of headers
    canonical_names = Column(Text, nullable=True)  # CNAME records
    is_virtual_host = Column(String(10), nullable=True, default='false')  # true/false
    uri = Column(String(500), nullable=True)  # Full URI
    
    # Probing status
    is_online = Column(String(50), nullable=True)  # online_http, online_https, online_both, offline, dns_only, pending
    probe_http_status = Column(Integer, nullable=True)  # HTTP status code from probing
    probe_https_status = Column(Integer, nullable=True)  # HTTPS status code from probing

    # Relationship
    scan_subdomains = relationship("ScanSubdomain", back_populates="subdomain", cascade="all, delete-orphan")

    def to_dict(self):
        return {
            'id': self.id,
            'subdomain': self.subdomain,
            'target_domain': self.target_domain,
            'discovered_at': self.last_seen_at.isoformat() if self.last_seen_at else None,
            'size': self.size,
            'status_code': self.status_code,
            'headers': self.headers,
            'canonical_names': self.canonical_names,
            'is_virtual_host': self.is_virtual_host,
            'uri': self.uri or (f"https://{self.subdomain}" if self.subdomain else None),
            'is_online': self.is_online,
            'probe_http_status': self.probe_http_status,
            'probe_https_status': self.probe_https_status
        }


class ScanSubdomain(Base):
    __tablename__ = 'scan_subdomains'
    __table_args__ = (
        UniqueConstraint('scan_id', 'subdomain_id', name='unique_scan_subdomain'),
        Index('idx_scan_subdomain_scan', 'scan_id'),
        Index('idx_scan_subdomain_subdomain', 'subdomain_id'),
        Index('idx_scan_subdomain_discovered', 'discovered_at'),
        Index('idx_scan_subdomain_scan_discovered', 'scan_id', 'discovered_at'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    scan_id = Column(Integer, ForeignKey('scans.id'), nullable=False)
    subdomain_id = Column(Integer, ForeignKey('subdomains.id'), nullable=False)
    discovered_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    tool_name = Column(String(100), nullable=True)  # Tool that discovered this subdomain

    # Relationships
    scan = relationship("Scan", back_populates="scan_subdomains")
    subdomain = relationship("Subdomain", back_populates="scan_subdomains")

    def to_dict(self):
        return {
            'id': self.subdomain.id,
            'scan_id': self.scan_id,
            'subdomain': self.subdomain.subdomain,
            'target_domain': self.subdomain.target_domain,
            'discovered_at': self.discovered_at.isoformat() if self.discovered_at else None,
            'tool_name': self.tool_name,
            'size': self.subdomain.size,
            'status_code': self.subdomain.status_code,
            'headers': self.subdomain.headers,
            'canonical_names': self.subdomain.canonical_names,
            'is_virtual_host': self.subdomain.is_virtual_host,
            'uri': self.subdomain.uri or (f"https://{self.subdomain.subdomain}" if self.subdomain.subdomain else None),
            'is_online': self.subdomain.is_online,
            'probe_http_status': self.subdomain.probe_http_status,
            'probe_https_status': self.subdomain.probe_https_status
        }


class Setting(Base):
    __tablename__ = 'settings'

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(255), unique=True, nullable=False, index=True)
    value = Column(Text, nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    def to_dict(self):
        return {
            'key': self.key,
            'value': self.value,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
