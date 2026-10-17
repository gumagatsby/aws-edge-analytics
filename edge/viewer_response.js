// Keeps a new visitor in the group the viewer-request function chose, by setting
// a cookie. Same hash, same inputs, so the same answer.
function bucket(text) {
    var h = 0x811c9dc5;
    for (var i = 0; i < text.length; i++) {
        h ^= text.charCodeAt(i);
        h = Math.imul(h, 0x01000193) >>> 0;
    }
    return h % 2 === 0 ? 'A' : 'B';
}

function handler(event) {
    var response = event.response;
    var cookie = event.request.cookies.ab;
    if (!cookie || (cookie.value !== 'A' && cookie.value !== 'B')) {
        var ua = event.request.headers['user-agent'] ? event.request.headers['user-agent'].value : '';
        response.cookies.ab = {
            value: bucket(event.viewer.ip + '|' + ua),
            attributes: 'Path=/; Max-Age=2592000; Secure; SameSite=Lax',
        };
    }
    return response;
}
