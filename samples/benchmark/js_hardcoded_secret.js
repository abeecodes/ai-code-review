const API_KEY = 'FAKEKEY_51H8fakeKEY1234567890abcdef';

function authHeader() {
  return { Authorization: 'Bearer ' + API_KEY };
}

module.exports = { authHeader };
