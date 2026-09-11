const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../app/static/js/image_upload.js'), 'utf8');

function setup({fail = false, outputSize = 100000, outputType = 'image/jpeg', replace = true} = {}) {
  const canvases = [], options = [];
  let closed = 0;
  const context = vm.createContext({
    File,
    DataTransfer: class {
      constructor() { this.files = []; this.items = {add: file => this.files.push(file)}; }
    },
    window: {createImageBitmap: async (file, opts) => {
      options.push(opts);
      if (fail) throw new Error('decode failed');
      return {width: 4000, height: 3000, close: () => closed++};
    }},
    document: {createElement: () => {
      const canvas = {getContext: () => ({drawImage(bitmap, x, y, width, height) {
        canvas.drawn = [width, height];
      }}), toBlob: callback => callback(new Blob([new Uint8Array(outputSize)], {type: outputType}))};
      canvases.push(canvas); return canvas;
    }},
  });
  if (!replace) context.DataTransfer = undefined;
  vm.runInContext(source, context);
  return {prepare: context.window.preparePostImages, canvases, options, closed: () => closed};
}
const photo = (type = 'image/jpeg', size = 1000000) => new File([new Uint8Array(size)], type === 'image/jpeg' ? 'photo.jpg' : 'image.png', {type});
const form = files => {
  const input = {files};
  return {input, querySelectorAll: () => [input]};
};

test('large JPEG shrinks without cropping and preserves filename and orientation setting', async () => {
  const env = setup(), original = photo(), target = form([original]);
  await env.prepare(target);
  assert.equal(target.input.files[0].size, 100000);
  assert.equal(target.input.files[0].name, original.name);
  assert.deepEqual(env.canvases[0].drawn, [1600, 1200]);
  assert.equal(env.options[0].imageOrientation, 'from-image');
  assert.equal(env.closed(), 1);
  assert.equal(env.canvases[0].width, 0);
  await env.prepare(target);
  assert.equal(env.canvases.length, 1);
});

test('small JPEGs and other formats remain untouched', async () => {
  const env = setup(), files = [photo('image/jpeg', 100000), photo('image/png'), photo('image/gif')];
  const target = form(files);
  await env.prepare(target);
  assert.deepEqual(target.input.files, files);
  assert.equal(env.canvases.length, 0);
});

for (const options of [{fail: true}, {outputSize: 2000000}, {outputType: 'image/png'}, {replace: false}]) {
  test(`retains original selection on unsupported or unhelpful conversion ${JSON.stringify(options)}`, async () => {
    const env = setup(options), original = photo(), target = form([original]);
    await env.prepare(target);
    assert.equal(target.input.files[0], original);
  });
}
