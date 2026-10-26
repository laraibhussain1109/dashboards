"""Private source storage, editable drafts and immutable public snapshots."""
import uuid
from django.db import models


class ImportJob(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.CharField(max_length=64, db_index=True)
    filename = models.CharField(max_length=255)
    source_type = models.CharField(max_length=20)
    source_url = models.CharField(max_length=2048, blank=True)
    source = models.FileField(upload_to='sources/%Y/%m/')
    tables = models.JSONField(default=list)
    warnings = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)


class Dataset(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.CharField(max_length=64, db_index=True)
    name = models.CharField(max_length=160)
    source_type = models.CharField(max_length=20)
    source_import = models.ForeignKey(ImportJob, on_delete=models.SET_NULL, null=True, related_name='datasets')
    source_table = models.CharField(max_length=255, blank=True)
    records = models.JSONField(default=list)
    profile_data = models.JSONField(default=dict)
    type_overrides = models.JSONField(default=dict)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class Dashboard(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.CharField(max_length=64, db_index=True)
    title = models.CharField(max_length=160)
    description = models.TextField(blank=True)
    config = models.JSONField(default=dict)
    revision = models.PositiveIntegerField(default=1)
    slug = models.SlugField(max_length=200, unique=True, null=True, blank=True)
    active_version = models.PositiveIntegerField(default=0)
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class Publication(models.Model):
    dashboard = models.ForeignKey(Dashboard, on_delete=models.CASCADE, related_name='publications')
    version = models.PositiveIntegerField()
    title = models.CharField(max_length=160)
    description = models.TextField(blank=True)
    config = models.JSONField(default=dict)
    datasets = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['dashboard', 'version'], name='unique_publication_version')]
        ordering = ['-version']
