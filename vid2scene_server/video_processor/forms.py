from django import forms
from django.core.exceptions import ValidationError
from django.conf import settings
import logging
from .models import SceneProcessingJob
from subscriptions.utils import user_can_generate_premium_scene

logger = logging.getLogger(__name__)


class RangeNumberWidget(forms.MultiWidget):
    """A widget that combines a range slider with a number input"""
    
    def __init__(self, attrs=None):
        widgets = [
            forms.NumberInput(),
            forms.NumberInput(attrs={'type': 'range', 'class': 'slider'})
        ]
        super().__init__(widgets, attrs)
    
    def decompress(self, value):
        if value:
            return [value, value]
        return [None, None]
        
    def value_from_datadict(self, data, files, name):
        values = super().value_from_datadict(data, files, name)
        # Use the number input value if provided, otherwise the range value
        return values[0] or values[1]


class VideoUploadForm(forms.ModelForm):
    use_background_sphere = forms.BooleanField(required=False, initial=True, label="Use Gaussian Fibonacci Sphere")
    
    def __init__(self, *args, **kwargs):
        # Extract user from kwargs before calling super()
        user = kwargs.pop('user', None)
        self.user = user  # Store user for validation methods
        
        # Explicitly set initial data
        if 'initial' not in kwargs:
            kwargs['initial'] = {}
        kwargs['initial'].update({
            'training_max_num_gaussians': SceneProcessingJob.DEFAULT_NUM_GAUSSIANS,
            'training_num_steps': SceneProcessingJob.DEFAULT_NUM_STEPS
        })
        super().__init__(*args, **kwargs)
        
        # Determine max values based on user's premium status
        user_has_premium_access = user_can_generate_premium_scene(user, api=False) if user else False
        
        max_gaussians = SceneProcessingJob.MAX_NUM_GAUSSIANS if user_has_premium_access else SceneProcessingJob.MAX_NUM_GAUSSIANS_FREE
        max_steps = SceneProcessingJob.MAX_NUM_STEPS if user_has_premium_access else SceneProcessingJob.MAX_NUM_STEPS_FREE
        
        # Override the attr values here because, for some reason, Django model's PositiveIntegerField forces 
        # the min to be 0 regardless what we put in the Meta class widget attrs.
        # See: https://forum.djangoproject.com/t/when-i-define-a-range-control-widget-min-value-isnt-being-utilized/17276/16
        self.fields['training_max_num_gaussians'].widget.attrs.update({
            'min': SceneProcessingJob.MIN_NUM_GAUSSIANS,
            'max': max_gaussians,
            'value': SceneProcessingJob.DEFAULT_NUM_GAUSSIANS,
            'step': 10000
        })
        self.fields['training_num_steps'].widget.attrs.update({
            'min': SceneProcessingJob.MIN_NUM_STEPS,
            'max': max_steps,
            'value': SceneProcessingJob.DEFAULT_NUM_STEPS,
            'step': 1000
        })
        
        # Only show GLOMAP and VGGT (hide COLMAP for now)
        self.fields['reconstruction_method'].choices = [
            (SceneProcessingJob.ReconstructionMethod.GLOMAP, 
             SceneProcessingJob.ReconstructionMethod.GLOMAP.label),
            (SceneProcessingJob.ReconstructionMethod.VGGT, 
             SceneProcessingJob.ReconstructionMethod.VGGT.label)
        ]
    
    class Meta:
        model = SceneProcessingJob
        fields = ["video_file", "title", "public", "allow_as_example", "remove_background", "equirectangular", "use_background_sphere", "reconstruction_method", "training_max_num_gaussians", "training_num_steps", "apriltag_size_mm"]
        widgets = {
            'video_file': forms.ClearableFileInput(attrs={'accept': 'video/*'}),
            'reconstruction_method': forms.Select(attrs={'class': 'form-select'}),
            'training_max_num_gaussians': RangeNumberWidget(attrs={
                'autocomplete': 'off'
            }),
            'training_num_steps': RangeNumberWidget(attrs={
                'autocomplete': 'off'
            }),
            'apriltag_size_mm': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g 95.0',
                'step': '0.1',
                'min': '1.0',
                'max': '1000.0'
            })
        }

    def clean_video_file(self):
        logger.info("Validating video file.")
        file = self.cleaned_data.get('video_file')

        if not file:
            raise ValidationError("No file was uploaded.")

        # Validate file size
        user_has_premium_access = user_can_generate_premium_scene(self.user, api=False) if self.user else False
        if user_has_premium_access:
            max_size = settings.MAX_VIDEO_FILE_SIZE_PRO
        else:
            max_size = settings.MAX_VIDEO_FILE_SIZE_FREE

        if file.size > max_size:
            logger.info(f"File size exceeds the maximum allowed limit ({max_size} bytes).")
            raise ValidationError("File size exceeds the maximum allowed limit.")

        # Validate MIME type
        if not file.content_type.startswith('video/'):
            logger.info("Uploaded file is not a valid video.")
            raise ValidationError("Uploaded file is not a valid video.")

        return file
    
    def clean(self):
        cleaned_data = super().clean()
        apriltag_size = cleaned_data.get('apriltag_size_mm')
        
        # Check if AprilTag calibration is requested (size provided)
        if apriltag_size is not None:
            # Verify user is enterprise (either tier)
            if hasattr(self, 'user') and self.user:
                user_is_enterprise = is_enterprise_user(self.user) or is_enterprise_perscene_user(self.user)
            else:
                user_is_enterprise = False
            
            if not user_is_enterprise:
                raise ValidationError("AprilTag calibration is only available for Enterprise users.")
            
            # Verify tag size is reasonable (validators will also check this)
            if apriltag_size < 1.0 or apriltag_size > 1000.0:
                raise ValidationError("AprilTag size must be between 1mm and 1000mm.")
        
        return cleaned_data


class QuestUploadForm(forms.ModelForm):
    """Form for uploading Quest project zip files."""
    
    def __init__(self, *args, **kwargs):
        # Extract user from kwargs before calling super()
        user = kwargs.pop('user', None)
        self.user = user  # Store user for validation methods
        
        # Explicitly set initial data using the standard default
        QUEST_DEFAULT_GAUSSIANS = SceneProcessingJob.DEFAULT_NUM_GAUSSIANS
        if 'initial' not in kwargs:
            kwargs['initial'] = {}
        kwargs['initial'].update({
            'training_max_num_gaussians': QUEST_DEFAULT_GAUSSIANS,
            'training_num_steps': SceneProcessingJob.DEFAULT_NUM_STEPS,
            'reconstruction_method': SceneProcessingJob.ReconstructionMethod.QUEST
        })
        super().__init__(*args, **kwargs)
        
        # Determine max values based on user's premium status
        user_has_premium_access = user_can_generate_premium_scene(user, api=False) if user else False
        
        max_gaussians = SceneProcessingJob.MAX_NUM_GAUSSIANS if user_has_premium_access else SceneProcessingJob.MAX_NUM_GAUSSIANS_FREE
        max_steps = SceneProcessingJob.MAX_NUM_STEPS if user_has_premium_access else SceneProcessingJob.MAX_NUM_STEPS_FREE
        
        # Override the attr values
        self.fields['training_max_num_gaussians'].widget.attrs.update({
            'min': SceneProcessingJob.MIN_NUM_GAUSSIANS,
            'max': max_gaussians,
            'value': QUEST_DEFAULT_GAUSSIANS,
            'step': 10000
        })
        self.fields['training_num_steps'].widget.attrs.update({
            'min': SceneProcessingJob.MIN_NUM_STEPS,
            'max': max_steps,
            'value': SceneProcessingJob.DEFAULT_NUM_STEPS,
            'step': 1000
        })
        
        # Force reconstruction method to QUEST
        self.fields['reconstruction_method'].initial = SceneProcessingJob.ReconstructionMethod.QUEST
        self.fields['reconstruction_method'].widget = forms.HiddenInput()
        
        # Change the label for video_file to "Scene File (ZIP)"
        self.fields['video_file'].label = "Scene File (ZIP)"
    
    class Meta:
        model = SceneProcessingJob
        fields = ["video_file", "title", "public", "allow_as_example", "reconstruction_method", "training_max_num_gaussians", "training_num_steps"]
        widgets = {
            'video_file': forms.ClearableFileInput(attrs={'accept': '.zip'}),
            'reconstruction_method': forms.HiddenInput(),
            'training_max_num_gaussians': RangeNumberWidget(attrs={
                'autocomplete': 'off'
            }),
            'training_num_steps': RangeNumberWidget(attrs={
                'autocomplete': 'off'
            }),
        }

    def clean_video_file(self):
        logger.info("Validating Quest zip file.")
        file = self.cleaned_data.get('video_file')

        if not file:
            raise ValidationError("No file was uploaded.")

        # Validate file extension
        file_name = file.name.lower()
        if not file_name.endswith('.zip'):
            logger.info("Uploaded file is not a zip file.")
            raise ValidationError("Uploaded file must be a .zip file.")

        return file
    
    def clean(self):
        cleaned_data = super().clean()
        # Force reconstruction method to QUEST
        cleaned_data['reconstruction_method'] = SceneProcessingJob.ReconstructionMethod.QUEST
        return cleaned_data

class GenerateLODUploadForm(forms.ModelForm):
    """Form for uploading raw PLY files to generate LOD streams."""
    
    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        self.user = user
        
        # Explicitly set initial data
        if 'initial' not in kwargs:
            kwargs['initial'] = {}
        kwargs['initial'].update({
            'training_max_num_gaussians': SceneProcessingJob.DEFAULT_NUM_GAUSSIANS,
            'training_num_steps': SceneProcessingJob.DEFAULT_NUM_STEPS,
            'reconstruction_method': SceneProcessingJob.ReconstructionMethod.GENERATE_LOD
        })
        super().__init__(*args, **kwargs)
        
        # Disable/hide unnecessary fields
        self.fields['reconstruction_method'].initial = SceneProcessingJob.ReconstructionMethod.GENERATE_LOD
        self.fields['reconstruction_method'].widget = forms.HiddenInput()
        
        self.fields['training_max_num_gaussians'].initial = SceneProcessingJob.DEFAULT_NUM_GAUSSIANS
        self.fields['training_max_num_gaussians'].widget = forms.HiddenInput()
        
        self.fields['training_num_steps'].initial = SceneProcessingJob.DEFAULT_NUM_STEPS
        self.fields['training_num_steps'].widget = forms.HiddenInput()
        
        # Change the label for video_file to "Input PLY File"
        self.fields['video_file'].label = "Splatted Scene (.ply)"
    
    class Meta:
        model = SceneProcessingJob
        fields = ["video_file", "title", "public", "allow_as_example", "reconstruction_method", "training_max_num_gaussians", "training_num_steps"]
        widgets = {
            'video_file': forms.ClearableFileInput(attrs={'accept': '.ply'}),
            'reconstruction_method': forms.HiddenInput(),
            'training_max_num_gaussians': forms.HiddenInput(),
            'training_num_steps': forms.HiddenInput(),
        }

    def clean_video_file(self):
        logger.info("Validating PLY file.")
        file = self.cleaned_data.get('video_file')

        if not file:
            raise ValidationError("No file was uploaded.")

        # Validate file size (6GB limit for LOD generation)
        MAX_PLY_UPLOAD_SIZE = 6 * 1024 * 1024 * 1024
        if file.size > MAX_PLY_UPLOAD_SIZE:
            logger.info(f"File size exceeds the maximum allowed limit for LOD generation ({MAX_PLY_UPLOAD_SIZE} bytes).")
            raise ValidationError(f"File size exceeds the 6GB maximum allowed limit.")

        # Validate file extension
        file_name = file.name.lower()
        if not file_name.endswith('.ply'):
            logger.info("Uploaded file is not a ply file.")
            raise ValidationError("Uploaded file must be a .ply file.")

        return file
    
    def clean(self):
        cleaned_data = super().clean()
        # Force reconstruction method to GENERATE_LOD
        cleaned_data['reconstruction_method'] = SceneProcessingJob.ReconstructionMethod.GENERATE_LOD
        return cleaned_data