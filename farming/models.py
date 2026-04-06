from django.db import models
from datetime import date

from master_data.models import Customer, Product, Village


class CropMaster(models.Model):
    CROP_TYPE_CHOICES = [
        ('KHARIF', 'Kharif'),
        ('RABI',   'Rabi'),
        ('BOTH',   'Both / Year-round'),
    ]

    name        = models.CharField(max_length=150, unique=True)
    crop_type   = models.CharField(max_length=10, choices=CROP_TYPE_CHOICES)
    is_active   = models.BooleanField(default=True)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class CropProductNorm(models.Model):
    """Standard application rate: 'Tomato needs 100 Kg of Urea per acre'."""

    crop             = models.ForeignKey(
        CropMaster, on_delete=models.CASCADE, related_name='norms'
    )
    product          = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name='crop_norms'
    )
    application_rate = models.DecimalField(max_digits=10, decimal_places=3,
                                           help_text='Quantity per acre')
    unit             = models.CharField(max_length=20,
                                        help_text='Unit of measurement (mirrors Product.unit_type)')
    notes            = models.TextField(blank=True)

    class Meta:
        unique_together = ('crop', 'product')

    def __str__(self):
        return (f"{self.crop.name} — {self.product.name} "
                f"@ {self.application_rate} {self.unit}/acre")


class CultivationRecord(models.Model):
    SEASON_CHOICES = [
        ('KHARIF', 'Kharif'),
        ('RABI',   'Rabi'),
    ]
    STATUS_CHOICES = [
        ('PLANNED',   'Planned'),
        ('ACTIVE',    'Active'),
        ('HARVESTED', 'Harvested'),
    ]

    customer    = models.ForeignKey(
        Customer, on_delete=models.CASCADE, related_name='cultivation_records'
    )
    crop        = models.ForeignKey(
        CropMaster, on_delete=models.PROTECT, related_name='cultivation_records'
    )
    acreage     = models.DecimalField(max_digits=8, decimal_places=2,
                                      help_text='Acres allocated to this crop')
    season      = models.CharField(max_length=10, choices=SEASON_CHOICES)
    season_year = models.PositiveIntegerField()
    status      = models.CharField(max_length=10, choices=STATUS_CHOICES,
                                   default='ACTIVE')
    notes       = models.TextField(blank=True)
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-season_year', 'season', 'crop__name']

    def __str__(self):
        return (f"{self.customer.name} — {self.crop.name} "
                f"({self.season} {self.season_year})")


# ============================================================================
# Ag-CDSS Phase 1 Models
# ============================================================================


class AgronomistProfile(models.Model):
    """Field officer/agronomist profile for consultation tracking."""

    class Designation(models.TextChoices):
        FIELD_OFFICER = 'field_officer', 'Field Officer'
        AGRONOMIST = 'agronomist', 'Senior Agronomist'
        CONSULTANT = 'consultant', 'Consultant'

    employee_id = models.CharField(
        max_length=20,
        unique=True,
        help_text='Unique employee identifier (e.g., EMP-001)'
    )
    name = models.CharField(max_length=100)
    designation = models.CharField(
        max_length=50,
        choices=Designation.choices,
        default=Designation.FIELD_OFFICER
    )
    zone = models.CharField(
        max_length=100,
        help_text='Geographic coverage area'
    )
    phone = models.CharField(max_length=15)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'farming_agronomist_profile'
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.get_designation_display()})"


class Plot(models.Model):
    """Physical land parcel owned by a customer."""

    class SoilType(models.TextChoices):
        SANDY = 'sandy', 'Sandy'
        LOAMY = 'loamy', 'Loamy'
        CLAY = 'clay', 'Clay'
        BLACK_COTTON = 'black_cotton', 'Black Cotton'

    customer = models.ForeignKey(
        Customer,
        on_delete=models.CASCADE,
        related_name='plots'
    )
    plot_name = models.CharField(
        max_length=100,
        help_text='Plot identifier (e.g., "North Field", "River Side")'
    )
    area_acres = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        help_text='Total area in acres'
    )
    village = models.ForeignKey(
        Village,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='plots'
    )
    soil_type = models.CharField(
        max_length=20,
        choices=SoilType.choices,
        blank=True,
        help_text='Soil classification'
    )
    gps_lat = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        verbose_name='GPS Latitude'
    )
    gps_lon = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        verbose_name='GPS Longitude'
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'farming_plot'
        ordering = ['customer', 'plot_name']
        constraints = [
            models.UniqueConstraint(
                fields=['customer', 'plot_name'],
                name='unique_customer_plot_name'
            )
        ]

    def __str__(self):
        return f"{self.customer.name} - {self.plot_name} ({self.area_acres}ac)"


class PestDiseaseLibrary(models.Model):
    """Master catalogue of pests, diseases, deficiencies, and weeds."""

    class Type(models.TextChoices):
        PEST = 'pest', 'Pest'
        DISEASE = 'disease', 'Disease'
        NUTRIENT_DEFICIENCY = 'deficiency', 'Nutrient Deficiency'
        WEED = 'weed', 'Weed'

    name = models.CharField(
        max_length=150,
        unique=True,
        help_text='Standard name of pest/disease'
    )
    local_name = models.CharField(
        max_length=150,
        blank=True,
        help_text='Local language name'
    )
    type = models.CharField(
        max_length=20,
        choices=Type.choices,
        help_text='Classification type'
    )
    affected_crops = models.ManyToManyField(
        CropMaster,
        through='PestDiseaseCropLink',
        blank=True,
        related_name='pest_diseases',
        help_text='Crops affected by this pest/disease'
    )
    symptoms = models.TextField(
        help_text='Visual indicators and symptoms'
    )
    management_notes = models.TextField(
        blank=True,
        help_text='General management and control notes'
    )
    photo = models.ImageField(
        upload_to='pest_disease/',
        null=True,
        blank=True,
        help_text='Reference photo'
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'farming_pest_disease_library'
        ordering = ['type', 'name']

    def __str__(self):
        return f"{self.name} ({self.get_type_display()})"


class PestDiseaseCropLink(models.Model):
    """Through model linking pests/diseases to crops for M2M relationship."""

    pest_disease = models.ForeignKey(
        PestDiseaseLibrary,
        on_delete=models.CASCADE,
        related_name='crop_links'
    )
    crop = models.ForeignKey(
        CropMaster,
        on_delete=models.CASCADE,
        related_name='pest_disease_links'
    )

    class Meta:
        db_table = 'farming_pest_disease_crop_link'
        unique_together = ['pest_disease', 'crop']

    def __str__(self):
        return f"{self.pest_disease.name} → {self.crop.name}"


class FieldVisit(models.Model):
    """Scheduled or conducted field visit to farmer's plot (appointment-like)."""

    class Purpose(models.TextChoices):
        ROUTINE = 'routine', 'Routine Scouting'
        COMPLAINT = 'complaint', 'Complaint'
        FOLLOW_UP = 'follow_up', 'Follow-up'
        SEASONAL = 'seasonal', 'Seasonal Assessment'

    class Status(models.TextChoices):
        SCHEDULED = 'scheduled', 'Scheduled'
        IN_PROGRESS = 'in_progress', 'In Progress'
        COMPLETED = 'completed', 'Completed'
        CANCELLED = 'cancelled', 'Cancelled'

    visit_number = models.CharField(
        max_length=20,
        unique=True,
        help_text='Auto-generated: FV-YYYYMMDD-NNNN'
    )
    customer = models.ForeignKey(
        Customer,
        on_delete=models.CASCADE,
        related_name='field_visits'
    )
    agronomist = models.ForeignKey(
        AgronomistProfile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='field_visits'
    )
    visit_date = models.DateField()
    visit_time = models.TimeField(
        null=True,
        blank=True
    )
    purpose = models.CharField(
        max_length=20,
        choices=Purpose.choices,
        default=Purpose.ROUTINE
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.SCHEDULED
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'farming_field_visit'
        ordering = ['-visit_date', '-created_at']

    def __str__(self):
        return f"{self.visit_number} - {self.customer.name} ({self.visit_date})"


class FieldConsultation(models.Model):
    """Primary clinical assessment document for agronomy consultation."""

    class Status(models.TextChoices):
        DRAFT = 'draft', 'Draft'
        SUBMITTED = 'submitted', 'Submitted'
        CLOSED = 'closed', 'Closed'

    consultation_number = models.CharField(
        max_length=20,
        unique=True,
        help_text='Auto-generated: FC-YYYYMMDD-NNNN'
    )
    field_visit = models.ForeignKey(
        FieldVisit,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='consultations'
    )
    customer = models.ForeignKey(
        Customer,
        on_delete=models.CASCADE,
        related_name='field_consultations'
    )
    agronomist = models.ForeignKey(
        AgronomistProfile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='consultations'
    )
    consultation_date = models.DateField(
        default=date.today
    )
    consultation_time = models.TimeField(
        null=True,
        blank=True
    )
    weather_conditions = models.CharField(
        max_length=50,
        blank=True,
        help_text='Clear / Overcast / Humid / Dry'
    )
    crop_stage = models.CharField(
        max_length=50,
        blank=True,
        help_text='Vegetative / Flowering / Fruiting / Pre-harvest'
    )
    general_observations = models.TextField(blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'farming_field_consultation'
        ordering = ['-consultation_date', '-created_at']

    def __str__(self):
        return f"{self.consultation_number} - {self.customer.name}"


class DiagnosisLine(models.Model):
    """Problem identification per crop plot within a consultation (child table)."""

    class Severity(models.TextChoices):
        LOW = 'low', 'Low'
        MEDIUM = 'medium', 'Medium'
        HIGH = 'high', 'High'
        CRITICAL = 'critical', 'Critical'

    consultation = models.ForeignKey(
        FieldConsultation,
        on_delete=models.CASCADE,
        related_name='diagnosis_lines'
    )
    cultivation_record = models.ForeignKey(
        CultivationRecord,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='diagnoses'
    )
    pest_disease = models.ForeignKey(
        PestDiseaseLibrary,
        on_delete=models.PROTECT,
        related_name='diagnosis_lines'
    )
    severity = models.CharField(
        max_length=10,
        choices=Severity.choices,
        default=Severity.MEDIUM
    )
    affected_area_acres = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        help_text='Portion of plot affected'
    )
    symptoms_observed = models.TextField(blank=True)
    field_photo = models.ImageField(
        upload_to='diagnosis/',
        null=True,
        blank=True
    )
    sequence = models.PositiveIntegerField(
        default=0,
        help_text='Row ordering'
    )

    class Meta:
        db_table = 'farming_diagnosis_line'
        ordering = ['sequence']

    def __str__(self):
        return f"{self.consultation.consultation_number} - {self.pest_disease.name} ({self.get_severity_display()})"


class PrescriptionLine(models.Model):
    """Chemical/fertilizer recommendation within a consultation (child table)."""

    class DosageUnit(models.TextChoices):
        KG = 'kg', 'Kilogram'
        LTR = 'ltr', 'Litre'
        ML = 'ml', 'Millilitre'
        GM = 'gm', 'Gram'
        PACKET = 'packet', 'Packet'

    class ApplicationMethod(models.TextChoices):
        SPRAY = 'spray', 'Spray'
        DRIP = 'drip', 'Drip Irrigation'
        BROADCAST = 'broadcast', 'Broadcast'
        SOIL = 'soil', 'Soil Application'
        SEED_TREATMENT = 'seed_treatment', 'Seed Treatment'

    class Status(models.TextChoices):
        RECOMMENDED = 'recommended', 'Recommended'
        DISPENSED = 'dispensed', 'Dispensed'
        APPLIED = 'applied', 'Applied'
        CANCELLED = 'cancelled', 'Cancelled'

    consultation = models.ForeignKey(
        FieldConsultation,
        on_delete=models.CASCADE,
        related_name='prescription_lines'
    )
    diagnosis_line = models.ForeignKey(
        DiagnosisLine,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='prescriptions'
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name='prescriptions'
    )
    dosage_per_acre = models.DecimalField(
        max_digits=8,
        decimal_places=3,
        help_text='Amount per acre'
    )
    dosage_unit = models.CharField(
        max_length=10,
        choices=DosageUnit.choices
    )
    total_quantity = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        help_text='Computed: dosage_per_acre × affected area'
    )
    application_method = models.CharField(
        max_length=20,
        choices=ApplicationMethod.choices,
        default=ApplicationMethod.SPRAY
    )
    timing = models.CharField(
        max_length=100,
        blank=True,
        help_text='e.g., "Morning spray", "At 30 DAS"'
    )
    frequency = models.CharField(
        max_length=100,
        blank=True,
        help_text='e.g., "Once", "Weekly × 3"'
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.RECOMMENDED
    )
    notes = models.TextField(blank=True)
    sequence = models.PositiveIntegerField(
        default=0,
        help_text='Row ordering'
    )

    class Meta:
        db_table = 'farming_prescription_line'
        ordering = ['sequence']

    def __str__(self):
        return f"{self.consultation.consultation_number} - {self.product.name} ({self.get_status_display()})"
