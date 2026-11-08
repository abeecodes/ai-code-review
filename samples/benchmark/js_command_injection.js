const { execSync } = require('child_process');

function listDir(dir) {
  return execSync('ls ' + dir).toString();
}

module.exports = { listDir };
