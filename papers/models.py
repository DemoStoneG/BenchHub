from django.db import models


class Paper(models.Model):
    title = models.CharField(max_length=500)
    arxiv_id = models.CharField(max_length=50, blank=True)
    local_pdf = models.FileField(upload_to='papers/')
    raw_markdown = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Status(models.TextChoices):
        PENDING = 'pending', '待解析'
        PROCESSING = 'processing', '解析中'
        COMPLETED = 'completed', '已完成'
        FAILED = 'failed', '失败'

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING
    )
    error_message = models.TextField(blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.title


class ExperimentRecord(models.Model):
    paper = models.ForeignKey(Paper, on_delete=models.CASCADE, related_name='results')
    dataset = models.CharField(max_length=100)
    model_name = models.CharField(max_length=100)
    metric = models.CharField(max_length=50)
    value = models.FloatField()
    is_verified = models.BooleanField(default=False)

    class Meta:
        ordering = ['dataset', 'model_name']

    def __str__(self):
        return f"{self.paper.title} - {self.model_name}@{self.dataset}.{self.metric}={self.value}"
