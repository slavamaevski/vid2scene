from django import forms
from .models import UserAPIKey


class APIKeyGenerationForm(forms.Form):
    name = forms.CharField(
        max_length=50,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'e.g., My App, Development, Production',
            'required': True
        }),
        help_text="Give your API key a descriptive name to help you identify it later."
    )
    
    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
    
    def clean_name(self):
        name = self.cleaned_data['name']
        # Check if name already exists for this user
        if UserAPIKey.objects.filter(user=self.user, name=name, revoked=False).exists():
            raise forms.ValidationError('An API key with this name already exists.')
        return name
