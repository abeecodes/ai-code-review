function average(numbers) {
  const total = numbers.reduce((a, b) => a + b, 0);
  return total / numbers.length;
}

module.exports = { average };
