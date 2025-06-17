export interface Patient {
  id: string;
  createdBy: number;
  fullName: string;
  dob: string;
  ssn: string;
  symptoms: string;
  clinicalNotes: string;
}

export const patients: Patient[] = [];

