// Dashboard.tsx
import React, { useEffect, useState } from 'react';
import { useAuth } from '../context/AuthContext';
import {
  Row,
  Col,
  Button,
  Table,
  Spinner,
  Form,
  Modal,
  Card,
  Collapse
} from 'react-bootstrap';

interface Patient {
  id: string;
  fullName: string;
  dob: string;
  ssn: string;
  symptoms: string;
  clinicalNotes: string;
}

const Dashboard = () => {
  const { user } = useAuth();
  const [patients, setPatients] = useState<Patient[]>([]);
  const [filtered, setFiltered] = useState<Patient[]>([]);
  const [form, setForm] = useState({ fullName: '', dob: '', ssn: '', symptoms: '', clinicalNotes: '' });
  const [loading, setLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);
  const [search, setSearch] = useState('');
  const [openFilter, setOpenFilter] = useState(true);

  const fetchPatients = () => {
    setLoading(true);
    fetch('/api/patients', {
      headers: { Authorization: btoa(`${user?.username}:${user?.username}123`) }
    })
      .then(res => res.json())
      .then(data => {
        setPatients(data);
        setFiltered(data);
        setLoading(false);
      });
  };

  useEffect(() => {
    if (user) fetchPatients();
  }, [user]);

  useEffect(() => {
    setFiltered(
      patients.filter(p => p.fullName.toLowerCase().includes(search.toLowerCase()))
    );
  }, [search, patients]);

  const handleCreate = (e: React.FormEvent) => {
    e.preventDefault();
    fetch('/api/patients', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: btoa(`${user?.username}:${user?.username}123`)
      },
      body: JSON.stringify(form)
    })
      .then(() => {
        setForm({ fullName: '', dob: '', ssn: '', symptoms: '', clinicalNotes: '' });
        setShowModal(false);
        fetchPatients();
      });
  };

  return (
    <>
      <Row className="mb-4">
        <Col xs={12} md={8} lg={6} className="mb-2">
          <h2>Welcome, {user?.username} <small className="text-muted">({user?.role})</small></h2>
        </Col>
        <Col xs={12} md={4} lg={6} className="text-md-end">
          {user?.role === 'clinician' && (
            <Button variant="primary" onClick={() => setShowModal(true)}>
              + Add Patient
            </Button>
          )}
        </Col>
      </Row>

      <Row className="mb-3 align-items-center">
        <Col xs={12} lg={8}>
          <h4>Patient Records</h4>
        </Col>
        <Col xs={12} lg={4} className="text-lg-end">
          <Button
            variant="outline-secondary"
            size="sm"
            onClick={() => setOpenFilter(!openFilter)}
            aria-controls="filter-collapse"
            aria-expanded={openFilter}
          >
            {openFilter ? 'Hide Filters' : 'Show Filters'}
          </Button>
        </Col>
      </Row>

      <Collapse in={openFilter} className="mb-4">
        <div id="filter-collapse">
          <Card body>
            <Form>
              <Row>
                <Col xs={12} md={6} lg={4} className="mb-3">
                  <Form.Control
                    placeholder="Search by Name"
                    value={search}
                    onChange={e => setSearch(e.target.value)}
                  />
                </Col>
              </Row>
            </Form>
          </Card>
        </div>
      </Collapse>

      {loading ? (
        <div className="d-flex justify-content-center align-items-center" style={{ minHeight: '300px' }}>
          <Spinner animation="border" />
        </div>
      ) : (
        <Table hover responsive className="mb-4">
          <thead className="table-dark">
            <tr>
              <th>Full Name</th>
              <th>DOB</th>
              <th>SSN</th>
              <th>Symptoms</th>
              <th>Clinical Notes</th>
            </tr>
          </thead>
          <tbody>
            {filtered.length ? (
              filtered.map(p => (
                <tr key={p.id}>
                  <td>{p.fullName}</td>
                  <td>{p.dob}</td>
                  <td>{p.ssn}</td>
                  <td>{p.symptoms}</td>
                  <td>{p.clinicalNotes}</td>
                </tr>
              ))
            ) : (
              <tr>
                <td colSpan={5} className="text-center text-muted">No records found</td>
              </tr>
            )}
          </tbody>
        </Table>
      )}

      <Modal show={showModal} onHide={() => setShowModal(false)} size="lg" centered>
        <Modal.Header closeButton>
          <Modal.Title>Add Patient</Modal.Title>
        </Modal.Header>
        <Modal.Body>
          <Form onSubmit={handleCreate}>
            <Row className="g-4">
              <Col xs={12} md={6}>
                <Form.Group>
                  <Form.Label>Full Name</Form.Label>
                  <Form.Control
                    value={form.fullName}
                    onChange={e => setForm({ ...form, fullName: e.target.value })}
                    required
                  />
                </Form.Group>
              </Col>
              <Col xs={12} md={6}>
                <Form.Group>
                  <Form.Label>Date of Birth</Form.Label>
                  <Form.Control
                    type="date"
                    value={form.dob}
                    onChange={e => setForm({ ...form, dob: e.target.value })}
                    required
                  />
                </Form.Group>
              </Col>
              <Col xs={12} md={6}>
                <Form.Group>
                  <Form.Label>SSN</Form.Label>
                  <Form.Control
                    value={form.ssn}
                    onChange={e => setForm({ ...form, ssn: e.target.value })}
                    required
                  />
                </Form.Group>
              </Col>
              <Col xs={12} md={6}>
                <Form.Group>
                  <Form.Label>Symptoms</Form.Label>
                  <Form.Control
                    value={form.symptoms}
                    onChange={e => setForm({ ...form, symptoms: e.target.value })}
                  />
                </Form.Group>
              </Col>
              <Col xs={12}>
                <Form.Group>
                  <Form.Label>Clinical Notes</Form.Label>
                  <Form.Control
                    as="textarea"
                    rows={3}
                    value={form.clinicalNotes}
                    onChange={e => setForm({ ...form, clinicalNotes: e.target.value })}
                  />
                </Form.Group>
              </Col>
            </Row>
            <div className="mt-4 text-end">
              <Button type="submit" variant="success">Save</Button>
            </div>
          </Form>
        </Modal.Body>
      </Modal>
    </>
  );
};

export default Dashboard;
