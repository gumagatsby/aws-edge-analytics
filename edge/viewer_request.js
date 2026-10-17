import cf from 'cloudfront';

// Rendered by Terraform: when true, tracking parameters are removed before the
// cache lookup, so /p/1?utm_source=x and /p/1 share one cache entry.
var NORMALISE = ${normalise};
var TRACKING = ['utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content', 'gclid', 'fbclid', 'msclkid'];
var HOMEPAGE = { '/': true, '/index.html': true };

// FNV-1a. The viewer-response function uses the same hash on the same inputs,
// so both agree on a new visitor's group without any shared state.
function bucket(text) {
    var h = 0x811c9dc5;
    for (var i = 0; i < text.length; i++) {
        h ^= text.charCodeAt(i);
        h = Math.imul(h, 0x01000193) >>> 0;
    }
    return h % 2 === 0 ? 'A' : 'B';
}

function variantFor(event) {
    var cookie = event.request.cookies.ab;
    if (cookie && (cookie.value === 'A' || cookie.value === 'B')) {
        return { group: cookie.value, assigned: false };
    }
    var ua = event.request.headers['user-agent'] ? event.request.headers['user-agent'].value : '';
    return { group: bucket(event.viewer.ip + '|' + ua), assigned: true };
}

function handler(event) {
    var request = event.request;
    var v = variantFor(event);

    // Group B sees the redesigned homepage. The rewrite happens before the cache
    // lookup, so each design is cached separately.
    if (HOMEPAGE[request.uri]) {
        request.uri = v.group === 'B' ? '/variants/b/index.html' : '/index.html';
    } else if (request.uri.charAt(request.uri.length - 1) === '/') {
        // Other folders (the insights dashboard) serve their own index page.
        request.uri += 'index.html';
    }

    var removed = 0;
    if (NORMALISE) {
        for (var i = 0; i < TRACKING.length; i++) {
            if (request.querystring[TRACKING[i]]) {
                delete request.querystring[TRACKING[i]];
                removed++;
            }
        }
    }

    // Lands in the viewer-request-log-data field of the access log.
    cf.logCustomData('ab=' + v.group + (v.assigned ? ';new=1' : '') + (removed ? ';stripped=' + removed : ''));
    return request;
}
