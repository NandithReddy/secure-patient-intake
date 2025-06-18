// cypress/e2e/dashboard.cy.ts

describe('Dashboard Page', () => {
  beforeEach(() => {
    cy.visit('/login');
    cy.get('input[placeholder="Username"]').type('clinician');
    cy.get('input[placeholder="Password"]').type('clinician123');
    cy.contains('button', 'Login').click();
    cy.url().should('include', '/dashboard');
  });

  it('shows welcome message and patient table', () => {
    cy.contains('Welcome, clinician');
    cy.get('table').should('exist');
    cy.get('th').contains('Name');
    cy.get('th').contains('DOB');
    cy.get('th').contains('SSN');
    cy.get('th').contains('Actions');
  });

  it('searches for a patient', () => {
    // Add a patient first
    cy.contains('+ Add Patient').click();
    cy.get('input[aria-label="Full Name"]').type('Test Patient');
    cy.get('input[aria-label="DOB"]').type('1980-01-01');
    cy.get('input[aria-label="SSN"]').type('123-45-6789');
    cy.get('input[aria-label="Symptoms"]').type('Cough');
    cy.get('textarea[aria-label="Clinical Notes"]').type('No additional notes');
    cy.contains('button', 'Save Patient').click();
    cy.contains('Patient created');
    // Now search for the patient
    cy.get('input[aria-label="Search by name"]').type('Test');
    cy.get('table').contains('td', 'Test Patient');
  });

  it('opens add patient modal and closes it', () => {
    cy.contains('+ Add Patient').click();
    cy.get('.modal').should('be.visible');
    cy.get('.modal').contains('Add Patient');
    cy.get('.modal button.btn-close').click({ force: true });
    cy.get('.modal').should('not.exist');
  });
});
