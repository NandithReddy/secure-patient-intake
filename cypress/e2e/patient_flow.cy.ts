// cypress/e2e/patient_flow.cy.ts

describe('Patient Intake Flow', () => {
  beforeEach(() => {
    cy.visit('/login');
  });

  it('logs in as clinician and performs CRUD', () => {
    // 1) Login
    cy.get('input[placeholder="Username"]').type('clinician');
    cy.get('input[placeholder="Password"]').type('clinician123');
    cy.contains('button', 'Login').click();

    // should land on dashboard
    cy.url().should('include', '/dashboard');
    cy.contains('Welcome, clinician');

    // 2) Create a new patient
    cy.contains('+ Add Patient').click();
    cy.get('input[placeholder="Full Name"]').type('Test Patient');
    cy.get('input[type="date"]').type('1980-01-01');
    cy.get('input[placeholder="SSN"]').type('123-45-6789');
    cy.contains('button', 'Save Patient').click();
    cy.contains('Patient created');

    // 3) Edit that patient
    cy.contains('Test Patient').parents('tr').within(() => {
      cy.contains('Edit').click();
    });
    cy.get('input[placeholder="Full Name"]').clear().type('Test Patient X');
    cy.contains('button', 'Update Patient').click();
    cy.contains('Patient updated');
    cy.contains('Test Patient X');

    // 4) Delete the patient
    cy.contains('Test Patient X').parents('tr').within(() => {
      cy.contains('Delete').click();
    });
    cy.on('window:confirm', () => true);
    cy.contains('Patient deleted');
    cy.contains('Test Patient X').should('not.exist');
  });
});
