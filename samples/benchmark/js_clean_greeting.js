function greet(name = 'world') {
  if (typeof name !== 'string') {
    throw new TypeError('name must be a string');
  }
  return `Hello, ${name}!`;
}

module.exports = { greet };
