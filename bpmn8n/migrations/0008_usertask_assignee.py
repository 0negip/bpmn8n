from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("bpmn8n", "0007_event_data")]

    operations = [migrations.RenameField("usertask", "completed_by", "assignee")]
