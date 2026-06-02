import json
from rest_framework import serializers
from .models import SceneProcessingJob, CAMERA_DATA_SCHEMA
from jsonschema import validate, ValidationError as JsonSchemaValidationError
from django.core.exceptions import ValidationError as DjangoValidationError
from .utils import get_status_string, get_percent_complete, find_rq_job_with_queue_name

class JobListSerializer(serializers.ModelSerializer):
    """
    Lightweight serializer for job list operations - only returns job_id and title.
    """
    job_id = serializers.CharField(source='id', read_only=True)

    class Meta:
        model = SceneProcessingJob
        fields = ['job_id', 'title']

class JobDetailSerializer(serializers.ModelSerializer):
    """
    Single serializer for job detail GET and PATCH. Hides internal fields and
    file paths; exposes booleans and status.
    """
    job_id = serializers.CharField(source='id', read_only=True)
    status = serializers.SerializerMethodField()
    percent_complete = serializers.SerializerMethodField()
    has_ply = serializers.SerializerMethodField()
    has_spz = serializers.SerializerMethodField()
    camera_data = serializers.JSONField(required=False, allow_null=True)

    class Meta:
        model = SceneProcessingJob
        fields = [
            'job_id',
            'title',
            'status',
            'percent_complete',
            'uploaded_at',
            'public',
            'reconstruction_method',
            'training_max_num_gaussians',
            'training_num_steps',
            'remove_background',
            'has_ply',
            'has_spz',
            'camera_data',
        ]
        read_only_fields = [
            'job_id',
            'uploaded_at',
            'status',
            'percent_complete',
            'has_ply',
            'has_spz',
            'reconstruction_method',
            'training_max_num_gaussians',
            'training_num_steps',
            'remove_background',
        ]

    def validate_camera_data(self, value):
        if value is None:
            return value
        try:
            # If value is already a dict/list, use it directly
            # If it's a string, parse it
            json_value = value if isinstance(value, (dict, list)) else json.loads(value)
            validate(instance=json_value, schema=CAMERA_DATA_SCHEMA)
            return json_value  # Return the validated dict/list, not the original value
        except (JsonSchemaValidationError, json.JSONDecodeError) as e:
            raise DjangoValidationError(f"Invalid camera_data: {e.message}")

    def get_status(self, obj):
        job, _ = find_rq_job_with_queue_name(obj.rq_job_id)
        return get_status_string(obj, job)

    def get_percent_complete(self, obj):
        if obj.ply_file:
            return 100
        return get_percent_complete(obj)

    def get_has_ply(self, obj):
        return bool(getattr(obj, 'ply_file', None))

    def get_has_spz(self, obj):
        return bool(getattr(obj, 'spz_file', None))


 


 


 
