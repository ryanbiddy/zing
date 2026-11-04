const path = require("path");
process.argv = process.argv.map((arg, i) => i < 2 ? arg : path.resolve(arg));
process.chdir(__dirname);
require("../../src/myzing/_data/factory/render.cjs");
