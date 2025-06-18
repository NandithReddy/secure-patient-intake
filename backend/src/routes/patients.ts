// @ts-nocheck
const express = require('express');
const { v4: uuidv4 } = require('uuid');
const { patients } = require('../models/patient');
const { maskSSN } = require('../utils/maskSSN');
const { logAudit } = require('../services/auditLog');

const router = express.Router();

// Create new patient (only clinician)
router.post('/', (req: any, res: any) => {
  try {
    console.log('📝 POST /api/patients body:', req.body);
    console.log('👤 Authenticated user:', req.user);

    const user = req.user;
    if (!user) {
      return res.status(401).json({ message: 'Not authenticated' });
    }
    if (user.role !== 'clinician') {
      return res.status(403).json({ message: 'Forbidden' });
    }

    const { fullName, dob, ssn, symptoms, clinicalNotes } = req.body;
    if (!fullName || !dob || !ssn) {
      return res.status(400).json({ message: 'Missing required fields' });
    }

    const newPatient = {
      id: uuidv4(),
      createdBy: user.id,
      fullName,
      dob,
      ssn,
      symptoms: symptoms || '',
      clinicalNotes: clinicalNotes || ''
    };

    patients.push(newPatient);
    logAudit('CREATE_PATIENT', user.id, user.role, newPatient.id);

    return res.status(201).json({ message: 'Patient created', id: newPatient.id });
  } catch (err) {
    console.error('❌ Error in POST /api/patients:', err);
    return res.status(500).json({ message: 'Internal server error' });
  }
});

// Get all patients
router.get('/', (req: any, res: any) => {
  const user = req.user;
  const list = user.role === 'admin'
    ? patients
    : patients.filter((p: any) => p.createdBy === user.id);

  logAudit('VIEW_PATIENTS', user.id, user.role);

  const response = list.map((p: any) => ({
    ...p,
    ssn: user.role === 'admin' ? p.ssn : maskSSN(p.ssn)
  }));
  res.json(response);
});

// Get one patient
router.get('/:id', (req: any, res: any) => {
  const user = req.user;
  const patient = patients.find((p: any) => p.id === req.params.id);
  if (!patient) return res.status(404).json({ message: 'Not found' });

  if (user.role !== 'admin' && patient.createdBy !== user.id) {
    return res.status(403).json({ message: 'Forbidden' });
  }

  logAudit('VIEW_PATIENT', user.id, user.role, patient.id);

  res.json({
    ...patient,
    ssn: user.role === 'admin' ? patient.ssn : maskSSN(patient.ssn)
  });
});

// Edit patient
router.put('/:id', (req: any, res: any) => {
  const user = req.user;
  const idx = patients.findIndex((p: any) => p.id === req.params.id);
  if (idx === -1) return res.status(404).json({ message: 'Not found' });

  const patient = patients[idx];
  if (user.role !== 'admin' && patient.createdBy !== user.id) {
    return res.status(403).json({ message: 'Forbidden' });
  }

  const { fullName, dob, ssn, symptoms, clinicalNotes } = req.body;
  patients[idx] = { ...patient, fullName, dob, ssn, symptoms, clinicalNotes };
  logAudit('EDIT_PATIENT', user.id, user.role, patient.id);
  res.json({ message: 'Patient updated' });
});

// Delete patient
router.delete('/:id', (req: any, res: any) => {
  const user = req.user;
  const idx = patients.findIndex((p: any) => p.id === req.params.id);
  if (idx === -1) return res.status(404).json({ message: 'Not found' });

  const patient = patients[idx];
  if (user.role !== 'admin' && patient.createdBy !== user.id) {
    return res.status(403).json({ message: 'Forbidden' });
  }

  patients.splice(idx, 1);
  logAudit('DELETE_PATIENT', user.id, user.role, patient.id);
  res.json({ message: 'Patient deleted' });
});

module.exports = router;
