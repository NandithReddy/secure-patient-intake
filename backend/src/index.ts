// src/index.ts
import express from 'express';
import cors from 'cors';
import { json } from 'body-parser';

const authMiddleware = require('./middleware/auth').authMiddleware;
const patientRoutes = require('./routes/patients');

const app = express();

app.use(cors());
app.use(json());
app.use(authMiddleware);
app.use('/api/patients', patientRoutes);

const PORT = process.env.PORT || 5000;
app.listen(PORT, () => {
  console.log(`Backend server running on port ${PORT}`);
});
