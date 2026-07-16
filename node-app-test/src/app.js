const express = require('express');
const app = express();

app.use(express.json());

app.get('/health', (req, res) => {
  res.json({ status: 'ok' });
});

app.get('/greet/:name', (req, res) => {
  const { name } = req.params;
  res.json({ message: `Hello, ${name}!` });
});

app.get('/greet', (req, res) => {
  res.json({ message: 'Hello, World!' });
});

module.exports = app;