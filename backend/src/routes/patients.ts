const express = require('express');
const { v4: uuidv4 } = require('uuid');
const { patients, Patient } = require('../models/patient');
const { maskSSN } = require('../utils/maskSSN');
const { logAudit } = require('../services/auditLog');

const router = express.Router();

// Create new patient (only clinician can create)
router.post('/', (req: any, res: any) => {
  const user = req.user;

  if (user.role !== 'clinician') {
    return res.status(403).json({ message: 'Forbidden' });
  }

  const { fullName, dob, ssn, symptoms, clinicalNotes } = req.body;

  const newPatient = {
    id: uuidv4(),
    createdBy: user.id,
    fullName,
    dob,
    ssn,
    symptoms,
    clinicalNotes
  };

  patients.push(newPatient);
  logAudit('CREATE_PATIENT', user.id, user.role, newPatient.id);

  res.status(201).json({ message: 'Patient created successfully', id: newPatient.id });
});

// Get all patients
router.get('/', (req: any, res: any) => {
  const user = req.user;

  let result;

  if (user.role === 'admin') {
    result = patients;
  } else {
    result = patients.filter((p: any) => p.createdBy === user.id);
  }

  logAudit('VIEW_PATIENTS', user.id, user.role);

  const response = result.map((p: any) => ({
    ...p,
    ssn: user.role === 'admin' ? p.ssn : maskSSN(p.ssn)
  }));

  res.json(response);
});

// Get single patient by ID
router.get('/:id', (req: any, res: any) => {
  const user = req.user;
  const patient = patients.find((p: any) => p.id === req.params.id);

  if (!patient) {
    return res.status(404).json({ message: 'Patient not found' });
  }

  if (user.role !== 'admin' && patient.createdBy !== user.id) {
    return res.status(403).json({ message: 'Forbidden' });
  }

  logAudit('VIEW_PATIENT', user.id, user.role, patient.id);

  const response = {
    ...patient,
    ssn: user.role === 'admin' ? patient.ssn : maskSSN(patient.ssn)
  };

  res.json(response);
});

module.exports = router;

