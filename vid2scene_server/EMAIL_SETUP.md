# Email Notification Setup

This document explains how to set up email notifications for job completion and failure using SendGrid templates.

## Overview

The system sends email notifications to users when their video processing jobs complete successfully or fail. These emails use SendGrid's dynamic templates for professional-looking emails.

## Environment Variables

Add these environment variables to your `.env` file:

```bash
# SendGrid Template IDs (you'll get these after creating templates in SendGrid)
SENDGRID_JOB_COMPLETION_TEMPLATE_ID=d-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
SENDGRID_JOB_FAILURE_TEMPLATE_ID=d-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# Site URL for building links in emails
SITE_URL=https://vid2scene.com
```

## SendGrid Template Setup

### 1. Create Job Completion Template

1. Go to your SendGrid dashboard
2. Navigate to **Email API** > **Dynamic Templates**
3. Click **Create Template**
4. Name it "Job Completion Notification"
5. Use this HTML template:

```html
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Your video is ready!</title>
    <style>
        body { margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background-color: #f8f9fa; }
        .container { max-width: 600px; margin: 0 auto; background-color: #ffffff; }
        .header { background: linear-gradient(135deg, #5761d9 0%, #fd7e14 100%); padding: 40px 30px; text-align: center; }
        .header h1 { color: #ffffff; margin: 0; font-size: 28px; font-weight: 600; }
        .content { padding: 40px 30px; }
        .success-icon { width: 80px; height: 80px; background-color: #28a745; border-radius: 50%; display: inline-flex; align-items: center; justify-content: center; margin-bottom: 20px; }
        .success-icon::before { content: "✓"; color: white; font-size: 40px; font-weight: bold; }
        .greeting { font-size: 18px; color: #333; margin-bottom: 20px; }
        .job-details { background-color: #f8f9fa; border-radius: 8px; padding: 20px; margin: 20px 0; }
        .job-details h3 { margin: 0 0 15px 0; color: #333; font-size: 16px; }
        .job-details p { margin: 5px 0; color: #666; font-size: 14px; }
        .cta-button { display: inline-block; background: linear-gradient(135deg, #5761d9 0%, #fd7e14 100%); color: white; text-decoration: none; padding: 15px 30px; border-radius: 25px; font-weight: 600; font-size: 16px; margin: 20px 0; }
        .footer { background-color: #f8f9fa; padding: 30px; text-align: center; color: #666; font-size: 14px; }
        .unsubscribe { color: #999; text-decoration: none; font-size: 12px; }
        @media only screen and (max-width: 600px) {
            .container { margin: 0; }
            .header, .content, .footer { padding: 20px; }
            .header h1 { font-size: 24px; }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🎉 Your Scene is Ready!</h1>
        </div>
        
        <div class="content">

            <div class="greeting">
                Hi {{user_name}},
            </div>
            
            <p style="font-size: 16px; color: #333; line-height: 1.6; margin-bottom: 25px;">
                Great news! Your video has been successfully processed and your 3D scene is ready to explore.
            </p>
            
            <div class="job-details">
                <h3>📹 Job Details</h3>
                <p><strong>Video Title:</strong> {{job_title}}</p>
                <p><strong>Job ID:</strong> {{job_id}}</p>
                <p><strong>Uploaded:</strong> {{uploaded_at}}</p>
                <p><strong>Status Page:</strong> <a href="{{status_url}}" style="color: #5761d9; text-decoration: none;">View Job Status</a></p>
            </div>
            
            <div style="text-align: center; margin: 30px 0;">
                <a href="{{view_url}}" class="cta-button">
                    🚀 View Your 3D Scene
                </a>
            </div>
            
            <p style="font-size: 14px; color: #666; line-height: 1.5; margin-top: 25px;">
                Your 3D scene is now available for viewing and sharing. You can explore it from any angle, 
                take screenshots, and even share it with others.
            </p>
            
            <p style="font-size: 14px; color: #666; line-height: 1.5;">
                If you have any questions or need assistance, feel free to reach out to our support team at 
                <a href="mailto:contact@example.com" style="color: #5761d9; text-decoration: none;">contact@example.com</a>.
            </p>
        </div>
        
        <div class="footer">
            <p style="margin: 0 0 15px 0;">
                <strong>Vid2Scene</strong><br>
                Transform your videos into immersive 3D experiences
            </p>
            
            <div data-role="module-unsubscribe" class="module" role="module" data-type="unsubscribe" style="color:#444444; font-size:12px; line-height:20px; padding:16px 16px 16px 16px; text-align:Center;" data-muid="4e838cf3-9892-4a6d-94d6-170e474d21e5">
                <p style="font-size:12px; line-height:20px;">
                    <a class="Unsubscribe--unsubscribeLink" href="{{{unsubscribe}}}" target="_blank" style="font-family:sans-serif;text-decoration:none;">
                        Unsubscribe
                    </a>
                    -
                    <a href="{{{unsubscribe_preferences}}}" target="_blank" class="Unsubscribe--unsubscribePreferences" style="font-family:sans-serif;text-decoration:none;">
                        Unsubscribe Preferences
                    </a>
                </p>
            </div>
        </div>
    </div>
</body>
</html>

```

6. Design your email with these dynamic fields:
   - `{{user_name}}` - User's first name or username
   - `{{job_title}}` - Title of the video
   - `{{job_id}}` - Unique job ID
   - `{{view_url}}` - Direct link to view the processed scene
   - `{{uploaded_at}}` - When the video was uploaded

### 2. Create Job Failure Template

1. Create another template named "Job Failure Notification"
2. Design your email with these dynamic fields:
   - `{{user_name}}` - User's first name or username
   - `{{job_title}}` - Title of the video
   - `{{job_id}}` - Unique job ID
   - `{{error_message}}` - Error details
   - `{{uploaded_at}}` - When the video was uploaded

### 3. Get Template IDs

1. After creating each template, click on it
2. Copy the Template ID (starts with `d-`)
3. Add these IDs to your environment variables

## Email Content Suggestions

### Job Completion Email
- Subject: "Your video '{{job_title}}' is ready!"
- Content: Congratulate the user, provide the view link, mention processing time

### Job Failure Email
- Subject: "Video processing failed for '{{job_title}}'"
- Content: Apologize, explain the issue, suggest retrying or contacting support

## Testing

In development mode, emails will be logged to the console instead of being sent. Check your Django logs to see the email content.

## User Requirements

Emails are only sent to users who:
- Are authenticated (not anonymous)
- Have a verified email address
- Have an active account

## Troubleshooting

- Check Django logs for email sending errors
- Verify SendGrid API key is correct
- Ensure template IDs are valid
- Test with a verified email address 