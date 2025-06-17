import fs from 'fs';
import path from 'path';

const logFilePath = path.join(__dirname, '../logs/audit.log');

export function logAudit(action: string, userId: number, role: string, patientId?: string) {
  const logEntry = {
    timestamp: new Date().toISOString(),
    userId,
    role,
    action,
    patientId: patientId || null
  };

  fs.appendFileSync(logFilePath, JSON.stringify(logEntry) + '\\n');
}

