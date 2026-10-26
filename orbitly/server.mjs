import http from 'node:http';
import { readFile } from 'node:fs/promises';
import { extname, join, normalize } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('.', import.meta.url));
const port = Number(process.env.PORT || 3000);
const mime = {
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.webp': 'image/webp',
  '.svg': 'image/svg+xml',
  '.ico': 'image/x-icon'
};

const server = http.createServer(async (req, res) => {
  const requestPath = decodeURIComponent((req.url || '/').split('?')[0]);
  const routePages = { '/': 'index.html', '/chat': 'chat.html', '/login': 'login.html', '/signup': 'signup.html' };
  const relativePath = routePages[requestPath]
    || (requestPath === '/manus-routes.json' ? 'public/manus-routes.json' : normalize(requestPath).replace(/^[/\\]+/, ''));
  const candidate = join(root, relativePath);
  try {
    const data = await readFile(candidate);
    res.writeHead(200, { 'Content-Type': mime[extname(candidate)] || 'application/octet-stream' });
    res.end(data);
  } catch {
    if (!extname(requestPath)) {
      const data = await readFile(join(root, 'index.html'));
      res.writeHead(200, { 'Content-Type': mime['.html'] });
      res.end(data);
      return;
    }
    res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
    res.end('Not found');
  }
});

server.listen(port, '0.0.0.0', () => {
  console.log(`Orbitly preview listening on http://0.0.0.0:${port}`);
});
