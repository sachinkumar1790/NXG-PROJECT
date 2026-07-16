const request = require('supertest');
const app = require('./app');

describe('GET /health', () => {
  it('returns status ok', async () => {
    const res = await request(app).get('/health');
    expect(res.statusCode).toBe(200);
    expect(res.body).toEqual({ status: 'ok' });
  });
});

describe('GET /greet/:name', () => {
  it('returns greeting with name', async () => {
    const res = await request(app).get('/greet/Alfred');
    expect(res.statusCode).toBe(200);
    expect(res.body).toEqual({ message: 'Hello, Alfred!' });
  });

  it('returns generic greeting without name', async () => {
    const res = await request(app).get('/greet');
    expect(res.statusCode).toBe(200);
    expect(res.body).toEqual({ message: 'Hello, World!' });
  });
});