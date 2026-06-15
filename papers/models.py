from django.db import models


class Session(models.Model):
    """一个研究项目 / 对比会话。每个 session 内的论文与对比相互独立。"""
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']

    def __str__(self):
        return self.name


class Paper(models.Model):
    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name='papers')
    title = models.CharField(max_length=500)
    arxiv_id = models.CharField(max_length=50, blank=True)
    local_pdf = models.FileField(upload_to='papers/')
    raw_markdown = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Status(models.TextChoices):
        PENDING = 'pending', '待解析'
        EXTRACTING = 'extracting', '提取文本'
        CALLING_LLM = 'calling_llm', '调用 LLM'
        COMPLETED = 'completed', '已完成'
        FAILED = 'failed', '失败'

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING
    )
    progress_message = models.CharField(max_length=200, blank=True)
    error_message = models.TextField(blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.title


class ExperimentRecord(models.Model):
    paper = models.ForeignKey(Paper, on_delete=models.CASCADE, related_name='results')
    table_image = models.ForeignKey(
        'TableImage',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='records',
    )
    table_chunk = models.ForeignKey(
        'TableChunk',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='records',
    )
    benchmark = models.CharField(max_length=100, blank=True)
    dataset = models.CharField(max_length=100)
    model_name = models.CharField(max_length=100)
    metric = models.CharField(max_length=50)
    value = models.FloatField()
    is_verified = models.BooleanField(default=False)

    class Meta:
        ordering = ['benchmark', 'dataset', 'model_name']

    def __str__(self):
        return f"{self.paper.title} - {self.model_name}@{self.benchmark}/{self.dataset}.{self.metric}={self.value}"


class TableChunk(models.Model):
    """从 PDF 结构化提取的单张表格（PyMuPDF find_tables 主路径 + pymupdf4llm fallback）。

    - 同一逻辑大表跨多页 / 跨多子表时共享 table_n，靠 sub_table_index 区分
    - 段标题行（UDA / DG）单独成 chunk，sub_table_index>=1
    - 旧 markdown_text 保留为"展示用快照"，find_tables 路径写 Table.to_markdown()，
      fallback 路径写原 pymupdf4llm MD
    """
    paper = models.ForeignKey(Paper, on_delete=models.CASCADE, related_name='table_chunks')
    table_n = models.IntegerField()
    sub_table_index = models.IntegerField(default=0)
    page = models.IntegerField()
    caption = models.CharField(max_length=500, blank=True)
    markdown_text = models.TextField(blank=True)

    # 结构化数据（find_tables 路径填写）
    cells_json = models.JSONField(default=list, blank=True)
    header_json = models.JSONField(default=list, blank=True)
    bbox_json = models.JSONField(default=dict, blank=True)

    EXTRACTION_CHOICES = [
        ('docling', 'docling'),
        ('camelot_stream', 'camelot_stream'),
        ('camelot_lattice', 'camelot_lattice'),
        ('pymupdf_find_tables', 'pymupdf_find_tables'),
        ('pymupdf4llm', 'pymupdf4llm'),
    ]
    extraction_method = models.CharField(max_length=24, choices=EXTRACTION_CHOICES, default='camelot_stream')
    parent_table_n = models.IntegerField(null=True, blank=True)  # 子表指向所属大表的 table_n

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['paper', 'page', 'table_n', 'sub_table_index']
        unique_together = [('paper', 'table_n', 'sub_table_index')]

    def __str__(self):
        return f"Paper#{self.paper_id} Table {self.table_n}.{self.sub_table_index} @ p{self.page}"


class TableImage(models.Model):
    """从 PDF 中提取的表格截图，含 caption 与参与对比的标志"""
    paper = models.ForeignKey(Paper, on_delete=models.CASCADE, related_name='table_images')
    page_number = models.IntegerField()
    image = models.ImageField(upload_to='tables/')
    caption = models.CharField(max_length=500, blank=True)
    order = models.IntegerField(default=0)
    selected_for_compare = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['paper', 'page_number', 'order']

    def __str__(self):
        return f"Paper#{self.paper_id} p{self.page_number} #{self.id}"
