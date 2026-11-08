function sum(numbers) {
  if (!Array.isArray(numbers)) {
    throw new TypeError('numbers must be an array');
  }
  return numbers.reduce((a, b) => a + b, 0);
}

module.exports = { sum };
