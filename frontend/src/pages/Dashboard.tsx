import React, { useEffect, useState } from 'react';
import { useAuth } from '../context/AuthContext';
import {
  Button,
  Table,
  Spinner,
  Form,
  Modal,
  Toast,
  ToastContainer,
  Row,
  Col,
  Navbar,
  Container,
  Nav
} from 'react-bootstrap';
import './dashboard.css';

const API_BASE = 'http://localhost:5000';

interface Patient {
  id: string;
  fullName: string;
  dob: string;
  ssn: string;
  symptoms: string;
  clinicalNotes: string;
}

const Dashboard: React.FC = () => {
  const { user } = useAuth();
  const [patients, setPatients] = useState<Patient[]>([]);
  const [filtered, setFiltered] = useState<Patient[]>([]);
  const [form, setForm] = useState({ fullName: '', dob: '', ssn: '', symptoms: '', clinicalNotes: '' });
  const [loading, setLoading] = useState(false);
  const [showModal, setShowModal] = useState(false);
  const [editing, setEditing] = useState<Patient | null>(null);
  const [search, setSearch] = useState('');
  const [toast, setToast] = useState<{ show: boolean; message: string; variant: 'success' | 'danger' }>({ show: false, message: '', variant: 'success' });
  const [ssnError, setSsnError] = useState('');

  // Fetch patients from backend
  const fetchPatients = async () => {
    setLoading(true);
    try {
      const resp = await fetch(`${API_BASE}/api/patients`, {
        method: 'GET',
        headers: {
          'Content-Type': 'application/json',
          Authorization: btoa(`${user?.username}:${user?.username}123`)
        }
      });
      if (!resp.ok) {
        throw new Error(`Server returned ${resp.status}`);
      }
      const data: Patient[] = await resp.json();
      setPatients(data);
      setFiltered(data);
    } catch (err) {
      setToast({ show: true, message: 'Could not load patients', variant: 'danger' });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (user) fetchPatients();
  }, [user]);

  useEffect(() => {
    setFiltered(
      patients.filter(p => p.fullName.toLowerCase().includes(search.toLowerCase()))
    );
  }, [search, patients]);

  // Create or update patient
  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    // SSN validation: must be exactly 9 digits (ignore dashes)
    const ssnDigits = form.ssn.replace(/[^0-9]/g, '');
    if (ssnDigits.length !== 9) {
      setSsnError('SSN must be exactly 9 digits');
      return;
    } else {
      setSsnError('');
    }

    const method = editing ? 'PUT' : 'POST';
    const endpoint = editing
      ? `${API_BASE}/api/patients/${editing.id}`
      : `${API_BASE}/api/patients`;

    try {
      const resp = await fetch(endpoint, {
        method,
        headers: {
          'Content-Type': 'application/json',
          Authorization: btoa(`${user?.username}:${user?.username}123`)
        },
        body: JSON.stringify(form)
      });
      if (!resp.ok) {
        throw new Error(`Server returned ${resp.status}`);
      }
      // After creating a patient
      await resp.json();
      setToast({ show: true, message: editing ? 'Patient updated' : 'Patient created', variant: 'success' });
      setForm({ fullName: '', dob: '', ssn: '', symptoms: '', clinicalNotes: '' });
      setEditing(null);
      setShowModal(false);
      fetchPatients();
      // Audit log for create/update
      logAudit(editing ? 'update_patient' : 'create_patient');
    } catch (err) {
      setToast({ show: true, message: 'Error saving patient', variant: 'danger' });
    }
  };

  // Delete patient
  const handleDelete = async (patient: Patient) => {
    if (!window.confirm(`Delete ${patient.fullName}?`)) return;
    try {
      const resp = await fetch(`${API_BASE}/api/patients/${patient.id}`, {
        method: 'DELETE',
        headers: {
          Authorization: btoa(`${user?.username}:${user?.username}123`)
        }
      });
      if (!resp.ok) {
        throw new Error(`Server returned ${resp.status}`);
      }
      setToast({ show: true, message: 'Patient deleted', variant: 'success' });
      fetchPatients();
    } catch (err) {
      setToast({ show: true, message: 'Error deleting patient', variant: 'danger' });
    }
  };

  // Open edit modal
  const openEdit = (p: Patient) => {
    setEditing(p);
    setForm({ fullName: p.fullName, dob: p.dob, ssn: p.ssn, symptoms: p.symptoms, clinicalNotes: p.clinicalNotes });
    setShowModal(true);
  };

  // Utility to mask SSN
  const maskSSN = (ssn: string) => ssn ? `***-**-${ssn.slice(-4)}` : '';

  // Audit log function
  const logAudit = async (action: string, patientId?: string) => {
    try {
      await fetch(`${API_BASE}/api/audit`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: btoa(`${user?.username}:${user?.username}123`)
        },
        body: JSON.stringify({
          userId: user?.username,
          role: user?.role,
          action,
          patientId,
          timestamp: new Date().toISOString()
        })
      });
    } catch {}
  };

  // When viewing a patient (table row click)
  const handleView = (p: Patient) => {
    logAudit('view_patient', p.id);
    // Optionally, show a modal or details here
  };

  return (
    <div className="dashboard-root">
      {/* Modern Navbar */}
      <Navbar bg="white" expand="md" className="shadow-sm py-2 dashboard-navbar" fixed="top">
        <Container fluid>
          <Navbar.Brand style={{ fontWeight: 700, color: '#6366f1', fontSize: '1.5rem', letterSpacing: '1px' }}>
            <span style={{ color: '#0ea5e9' }}>Secure</span> Patient Intake
          </Navbar.Brand>
          <Navbar.Toggle aria-controls="dashboard-navbar-nav" />
          <Navbar.Collapse id="dashboard-navbar-nav">
            <Nav className="ms-auto align-items-center">
              <span className="me-3 text-secondary fw-semibold">{user?.username}</span>
              <Button variant="outline-primary" size="sm" onClick={() => { window.location.href = '/login'; }}>
                Logout
              </Button>
            </Nav>
          </Navbar.Collapse>
        </Container>
      </Navbar>
      <div className="dashboard-content" style={{ marginTop: '70px' }}>
        <div className="dashboard-card">
          {/* Welcome and Add Patient */}
          <Row className="align-items-center mb-3">
            <Col xs={12} md={8}>
              <h2 className="mb-0">Welcome, {user?.username}{user?.role === 'clinician' && " (Clinician)"}</h2>
            </Col>
            <Col xs={12} md={4} className="text-md-end mt-2 mt-md-0">
              {user?.role === 'clinician' && (
                <Button onClick={() => { setEditing(null); setForm({ fullName: '', dob: '', ssn: '', symptoms: '', clinicalNotes: '' }); setShowModal(true); }}>
                  + Add Patient
                </Button>
              )}
            </Col>
          </Row>
          {/* Search */}
          <Row className="mb-3">
            <Col xs={12} md={6}>
              <Form.Control
                placeholder="Search by name"
                aria-label="Search by name"
                value={search}
                onChange={e => setSearch(e.target.value)}
              />
            </Col>
          </Row>
          {/* Patient Table */}
          {loading ? (
            <div className="text-center"><Spinner animation="border" /></div>
          ) : (
            <Table hover responsive className="mb-0">
              <thead className="table-dark">
                <tr>
                  <th>Name</th>
                  <th>DOB</th>
                  <th>SSN</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map(p => (
                  <tr key={p.id} onClick={() => handleView(p)} style={{ cursor: 'pointer' }}>
                    <td>{p.fullName}</td>
                    <td>{p.dob}</td>
                    <td>{user?.role === 'clinician' ? p.ssn : maskSSN(p.ssn)}</td>
                    <td>
                      {user?.role === 'clinician' && (
                        <Button size="sm" variant="outline-info" className="me-2" onClick={e => { e.stopPropagation(); openEdit(p); }}>
                          Edit
                        </Button>
                      )}
                      {user?.role === 'clinician' && (
                        <Button size="sm" variant="outline-danger" onClick={e => { e.stopPropagation(); handleDelete(p); }}>
                          Delete
                        </Button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </div>
      </div>

      {/* Modal Form */}
      <Modal show={showModal} onHide={() => setShowModal(false)} centered>
        <Modal.Header closeButton>
          <Modal.Title>{editing ? 'Edit' : 'Add'} Patient</Modal.Title>
        </Modal.Header>
        <Modal.Body>
          <Form onSubmit={handleSubmit}>
            <Form.Group className="mb-2">
              <Form.Label>Full Name</Form.Label>
              <Form.Control aria-label="Full Name" required value={form.fullName} onChange={e => setForm({ ...form, fullName: e.target.value })} />
            </Form.Group>
            <Form.Group className="mb-2">
              <Form.Label>DOB</Form.Label>
              <Form.Control type="date" aria-label="DOB" required value={form.dob} onChange={e => setForm({ ...form, dob: e.target.value })} />
            </Form.Group>
            <Form.Group className="mb-2">
              <Form.Label>SSN</Form.Label>
              <Form.Control aria-label="SSN" required value={form.ssn} onChange={e => setForm({ ...form, ssn: e.target.value })} maxLength={11} />
              {ssnError && <div className="text-danger small mt-1">{ssnError}</div>}
            </Form.Group>
            <Form.Group className="mb-2">
              <Form.Label>Symptoms</Form.Label>
              <Form.Control aria-label="Symptoms" value={form.symptoms} onChange={e => setForm({ ...form, symptoms: e.target.value })} />
            </Form.Group>
            <Form.Group className="mb-2">
              <Form.Label>Clinical Notes</Form.Label>
              <Form.Control as="textarea" rows={3} aria-label="Clinical Notes" value={form.clinicalNotes} onChange={e => setForm({ ...form, clinicalNotes: e.target.value })} />
            </Form.Group>
            <Button type="submit" variant="success" className="w-100 mt-2">
              {editing ? 'Update Patient' : 'Save Patient'}
            </Button>
          </Form>
        </Modal.Body>
      </Modal>

      {/* Toast Notifications */}
      <ToastContainer position="bottom-end" className="p-3">
        <Toast bg={toast.variant} show={toast.show} onClose={() => setToast({ ...toast, show: false })} delay={3000} autohide>
          <Toast.Body className={toast.variant === 'danger' ? 'text-white' : ''}>
            {toast.message}
          </Toast.Body>
        </Toast>
      </ToastContainer>
    </div>
  );
};

export default Dashboard;