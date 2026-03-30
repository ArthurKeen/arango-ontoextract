# Healthcare Domain Model

## Overview

A healthcare system manages patients, clinical encounters, diagnoses, treatments, medications, medical devices, clinical trials, and the complex regulatory environment governing healthcare delivery. This document defines the core entities and relationships for a comprehensive healthcare ontology covering clinical, administrative, and research domains.

## Patients

A **Patient** is an individual receiving or registered to receive healthcare services:
- Medical record number (MRN) — institution-specific identifier
- National health identifier (e.g., NHS number, Medicare number)
- Demographics: full legal name, date of birth, gender, sex assigned at birth, preferred pronouns
- Contact information: addresses (home, mailing), phone numbers, email, emergency contact
- Insurance coverage: primary and secondary insurance plans, member ID, group number, coverage effective dates
- Primary care physician (PCP) assignment
- Advance directives: living will, healthcare proxy, do-not-resuscitate (DNR) status
- Organ donor registration
- Preferred language and interpreter requirements
- Disability accommodations
- Social determinants of health: housing status, food security, transportation access, education level, employment

### Patient History

**Medical History:** A chronological record of the patient's health:
- **Past Medical History (PMH)** — prior diagnoses, surgeries, hospitalizations
- **Family History** — medical conditions in biological relatives (parents, siblings, children) with age of onset
- **Social History** — smoking status (current, former, never; pack-years), alcohol use (drinks per week), substance use, exercise habits, occupation, sexual activity
- **Allergies** — allergen, reaction type (anaphylaxis, rash, GI upset), severity (mild, moderate, severe, life-threatening), verification status (confirmed, unconfirmed, refuted)
- **Immunization Record** — vaccine name, date administered, lot number, site, administering provider, next due date
- **Surgical History** — procedure name, date, surgeon, facility, outcome, complications

## Clinical Encounters

A **Clinical Encounter** (or Visit) is any interaction between a patient and a healthcare provider:
- Encounter ID, date/time, and duration
- Encounter type: office visit, emergency department, inpatient admission, telehealth, home visit, surgical procedure
- Facility and department/unit
- Attending provider and care team members
- Chief complaint (the patient's stated reason for the visit)
- Encounter status: planned, arrived, in-progress, on-leave, completed, cancelled, entered-in-error

### Encounter Types

**Outpatient Visit:**
- Appointment scheduling: requested slot, confirmed slot, check-in time, provider start time, provider end time
- Visit reason and ICD-10 diagnosis codes
- Clinical notes: history of present illness (HPI), review of systems (ROS), physical examination findings
- Assessment and plan
- Follow-up instructions and next appointment

**Emergency Department Visit:**
- Triage assessment: triage level (ESI 1-5), chief complaint, vital signs at triage
- Arrival mode: ambulance, walk-in, transfer from another facility
- Emergency Severity Index (ESI): 1 (resuscitation), 2 (emergent), 3 (urgent), 4 (less urgent), 5 (non-urgent)
- Disposition: discharged, admitted to inpatient, transferred, left against medical advice (AMA), deceased

**Inpatient Admission:**
- Admission type: emergency, urgent, elective, newborn
- Admitting diagnosis and principal diagnosis at discharge
- Assigned bed and unit (ICU, medical/surgical, obstetrics, pediatrics, psychiatric)
- Attending physician, resident/intern, consulting physicians
- Length of stay (LOS) in days
- Discharge disposition: home, skilled nursing facility, rehabilitation, hospice, deceased
- Discharge summary and discharge medication list

**Telehealth Visit:**
- Platform used (video, phone, asynchronous messaging)
- Technical quality: connection quality, audio/video issues
- Patient location (state/jurisdiction — important for licensing)
- Consent for telehealth on file

## Diagnoses and Conditions

A **Diagnosis** represents a clinical determination of a patient's condition:
- Diagnosis code: ICD-10-CM (e.g., E11.9 — Type 2 diabetes without complications)
- Diagnosis description and clinical context
- Diagnosis type: principal, secondary, admitting, working, differential, final
- Date of onset, date of diagnosis, date of resolution (if applicable)
- Severity: mild, moderate, severe
- Clinical status: active, recurrence, relapse, inactive, remission, resolved
- Verification status: confirmed, provisional, differential, refuted
- Diagnosing provider
- Body site (SNOMED CT body structure)
- Laterality: left, right, bilateral

**Chronic Condition** — a long-term diagnosis requiring ongoing management:
- Monitoring frequency and next review date
- Target metrics (e.g., HbA1c < 7% for diabetes, blood pressure < 130/80)
- Care plan reference
- Complications and comorbidities

**Problem List** — the curated list of a patient's active and historical conditions, maintained by the PCP:
- Problem rank (primary, secondary)
- Problem list entry date and resolution date
- Annotation notes

## Procedures and Treatments

A **Procedure** is a clinical activity performed on a patient:
- Procedure code: CPT (e.g., 99213 — established patient office visit), HCPCS, ICD-10-PCS (inpatient)
- Procedure description
- Date and time performed
- Performing provider and assisting providers
- Facility, operating room / procedure room
- Anesthesia type: general, regional (spinal, epidural), local, sedation, none
- Indication: the diagnosis or condition justifying the procedure
- Laterality and body site
- Outcome: successful, partially successful, unsuccessful, aborted
- Complications: intraoperative, postoperative
- Specimen collected (yes/no) — links to pathology

### Surgical Procedure Details

For surgical procedures, additional data:
- Pre-operative diagnosis and post-operative diagnosis
- Operative report: detailed narrative of the surgical procedure
- Implants placed: device identifier (UDI), model, manufacturer, lot number, serial number
- Blood loss estimate and transfusion requirement
- Wound classification: clean, clean-contaminated, contaminated, dirty
- Duration: incision time, closure time, total OR time
- Post-anesthesia care unit (PACU) time and recovery assessment

## Medications

A **Medication** is a pharmaceutical product:
- Drug name: brand name and generic name
- National Drug Code (NDC) or RxNorm concept unique identifier (RxCUI)
- Drug class (e.g., beta-blocker, ACE inhibitor, SSRI, antibiotic)
- Formulation: tablet, capsule, liquid, injection, patch, inhaler, topical
- Strength and unit (e.g., 500mg, 10mg/5mL)
- Route of administration: oral, intravenous, intramuscular, subcutaneous, topical, inhalation, rectal
- Manufacturer and NDC labeler code
- Controlled substance schedule (I through V) if applicable
- Black box warnings

### Medication Orders and Administration

**Medication Order (Prescription):**
- Ordering provider and ordering date
- Patient and encounter reference
- Medication reference (drug, strength, formulation)
- Dose and frequency (e.g., "500mg twice daily", "10 units at bedtime")
- Route of administration
- Duration: number of days, number of refills, or PRN (as needed)
- Instructions: "take with food", "avoid grapefruit juice", etc.
- DAW (dispense as written) flag — prevents generic substitution
- Prior authorization status (for insurance coverage)
- Indication: the diagnosis justifying the medication

**Medication Administration Record (MAR):**
- Medication given: drug, dose, route
- Administration date/time
- Administering nurse or provider
- Patient's vital signs before and after (for high-risk medications)
- Site of injection (for injectables)
- Waste verification (for controlled substances)

**Medication Reconciliation:** Comparison of medication lists at transitions of care:
- Home medication list (what the patient takes at home)
- Admission medication orders (what is ordered during hospitalization)
- Discharge medication list (what the patient should take after discharge)
- Discrepancies: additions, deletions, changes in dose/frequency, therapeutic substitutions

## Laboratory and Diagnostics

### Laboratory Tests

A **Laboratory Order** requests one or more lab tests:
- Ordering provider and clinical indication
- Specimen type: blood (whole blood, serum, plasma), urine, stool, cerebrospinal fluid, tissue, swab
- Specimen collection date/time and collector
- Specimen accession number (lab tracking ID)
- Priority: routine, stat, timed, ASAP

**Laboratory Result:**
- Test name and LOINC code (e.g., 2345-7 — Glucose [Mass/volume] in Serum or Plasma)
- Result value and unit of measure
- Reference range (normal range, critical range)
- Abnormal flag: normal, abnormal low, abnormal high, critically low, critically high
- Result status: preliminary, final, corrected, cancelled
- Performing laboratory and result date/time
- Interpretive comment (e.g., "consistent with iron deficiency anemia")

### Diagnostic Imaging

**Imaging Order:**
- Modality: X-ray, CT, MRI, ultrasound, PET, mammography, fluoroscopy, nuclear medicine
- Body part and laterality
- Clinical indication and relevant history
- Contrast: with contrast, without contrast, with and without contrast
- Patient preparation requirements (fasting, contrast allergy pre-medication)

**Imaging Report:**
- Radiologist (interpreting physician)
- Findings: structured description of observations
- Impression: summary interpretation and conclusion
- Comparison to prior studies
- Critical findings communicated to ordering provider (with communication timestamp)
- BIRADS category (for mammography): 0-6
- Recommendation: no follow-up, follow-up imaging in X months, biopsy recommended

## Healthcare Providers and Organizations

**Healthcare Provider:** An individual delivering healthcare services:
- National Provider Identifier (NPI) — 10-digit unique identifier
- Name, credentials (MD, DO, NP, PA, RN, PharmD, PT, etc.)
- Specialty (primary and secondary): internal medicine, cardiology, orthopedic surgery, etc.
- License number, state of licensure, license expiration
- DEA number (for controlled substance prescribing)
- Hospital privileges (at which facilities, privilege scope)
- Board certifications
- Practice group or employed physician organization

**Healthcare Organization:**
- Organization NPI and Tax ID
- Organization type: hospital, clinic, nursing home, home health agency, pharmacy, laboratory, imaging center
- Accreditation: Joint Commission, NCQA, AAAHC
- Network participation: in-network or out-of-network for each insurance plan
- Electronic health record (EHR) system in use
- Health information exchange (HIE) participation

## Insurance and Billing

**Insurance Plan:**
- Payer name and payer ID
- Plan type: HMO, PPO, POS, EPO, HDHP, Medicare (Parts A, B, C, D), Medicaid, Tricare, VA
- Coverage details: deductible, copay, coinsurance, out-of-pocket maximum
- Covered services and exclusions
- Prior authorization requirements by service category
- In-network and out-of-network benefit levels

**Claim:**
- Claim number, submission date, and payer
- Claim type: professional (CMS-1500), institutional (UB-04), dental, pharmacy
- Patient, provider, and facility references
- Service lines with CPT/HCPCS codes, ICD-10 diagnosis codes, dates of service, charges
- Adjudication: allowed amount, patient responsibility (copay, coinsurance, deductible), payer payment
- Claim status: submitted, pending, adjudicated, paid, denied, appealed

**Explanation of Benefits (EOB):** Payer's response to a claim:
- Services covered and amounts paid
- Patient responsibility breakdown
- Denial reasons with remark codes
- Appeal rights and deadline

## Clinical Trials and Research

**Clinical Trial:**
- Protocol identifier (NCT number from ClinicalTrials.gov)
- Study title and brief description
- Phase: Phase I, II, III, IV, or observational
- Study design: randomized, double-blind, placebo-controlled, crossover, cohort, case-control
- Principal investigator and sponsor (pharmaceutical company, NIH, academic institution)
- Institutional Review Board (IRB) approval number and approval date
- Enrollment target and current enrollment
- Inclusion and exclusion criteria
- Study arms: treatment groups with interventions assigned
- Primary and secondary endpoints (outcome measures)
- Informed consent document version and date

**Study Subject:**
- Subject ID (de-identified)
- Enrollment date and randomization assignment (arm/group)
- Screening results (eligibility confirmation)
- Visit schedule adherence
- Adverse events reported during the study
- Protocol deviations

**Adverse Event:**
- Event description and onset date
- Severity: mild, moderate, severe, life-threatening, death
- Causality assessment: definitely, probably, possibly, unlikely, unrelated to study drug
- Outcome: recovered, recovering, not recovered, fatal, unknown
- Serious Adverse Event (SAE) flag — requires expedited reporting to regulatory authorities
- Reporting to Data Safety Monitoring Board (DSMB)

## Relationships Summary

- A Patient **has** a Medical History, Allergies, and Immunization Record
- A Patient **participates in** Clinical Encounters
- A Clinical Encounter **is conducted by** Healthcare Providers at a Healthcare Organization
- A Diagnosis **is made during** a Clinical Encounter **for** a Patient
- A Procedure **is performed during** a Clinical Encounter **on** a Patient
- A Medication Order **is prescribed during** a Clinical Encounter **by** a Provider
- A Medication Administration **fulfills** a Medication Order
- A Laboratory Order **is placed during** a Clinical Encounter
- A Laboratory Result **responds to** a Laboratory Order
- An Imaging Order **results in** an Imaging Report
- A Patient **is covered by** one or more Insurance Plans
- A Claim **is submitted for** services rendered during a Clinical Encounter
- A Patient **may enroll in** a Clinical Trial as a Study Subject
- An Adverse Event **occurs to** a Study Subject **during** a Clinical Trial
- A Healthcare Provider **belongs to** a Healthcare Organization
- A Healthcare Provider **has** Licenses, Board Certifications, and Hospital Privileges
- A Chronic Condition **requires** a Care Plan **with** target metrics and monitoring frequency
- A Medication Reconciliation **compares** medication lists at transitions of care
- A Surgical Procedure **may involve** Implants with unique device identifiers
