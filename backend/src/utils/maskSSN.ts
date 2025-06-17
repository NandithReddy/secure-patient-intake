export function maskSSN(ssn: string): string {
  return `***-**-${ssn.slice(-4)}`;
}

