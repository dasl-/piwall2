import axios from 'axios';
import gapi from 'gapi-client';

// By default, include the port i.e. 'piwall.tv:666' in the api host to
// support running the piwall2 on a custom port
var api_host = window.location.host;
if (process.env.REACT_APP_API_HOST !== undefined) {
  api_host = process.env.REACT_APP_API_HOST;
} else {
  if (process.env.NODE_ENV === 'development') {
    if (window.location.hostname === 'localhost') {
      // 'localhost' indicates we are probably running the npm development server on a laptop / desktop computer
      // via `npm start --prefix app`
      api_host = 'piwall.tv'; // Default to this
    } else {
      // API url should not include the :3000 port that is present in the development server url
      api_host = window.location.hostname;
    }
  }
}

const client = axios.create({
  baseURL: "//" + api_host + "/api",
  json: true
});

//On load, called to load the auth2 library and API client library.
gapi.load('client', initGoogleClient);

// Initialize the API client library
function initGoogleClient() {
  gapi.client.init({
    apiKey: process.env.REACT_APP_GOOGLE_API_KEY,
    discoveryDocs: ["https://www.googleapis.com/discovery/v1/apis/youtube/v3/rest"],
  });
}

class APIClient {
  getQueue() {
    return this.perform('get', '/queue');
  }

  // Passing the id of the video to skip ensures our skips are "atomic". That is, we can ensure we skip the
  // video that the user intended to skip.
  nextVideo(playlist_video_id) {
    return this.perform('post', '/skip', {
      playlist_video_id: playlist_video_id
    });
  }

  removeVideo(video) {
    return this.perform('post', '/remove', {
      playlist_video_id: video.playlist_video_id
    });
  }

  setVolPct(vol_pct) {
    return this.perform('post', '/vol_pct', {
      vol_pct: vol_pct
    });
  }

  setScreensaverEnabled(is_enabled) {
    return this.perform('post', '/screensaver', {
      is_screensaver_enabled: is_enabled
    });
  }

  clearQueue() {
    return this.perform('post', '/clear');
  }

  enqueueVideo(video, color_mode) {
    return this.perform('post', '/queue', {
        url: video.video_url,
        color_mode: color_mode,
        thumbnail: video.thumbnail,
        title: video.title,
        duration: video.duration
    });
  }

  searchYoutube(query) {
    return gapi.client.youtube.search.list({
      "part": "snippet",
      "maxResults": 25,
      "q": query
    })
    .then(function(response) {
      var videos = response.result.items;
      var video_ids = '';
      for (var i in videos) {
        var video = videos[i];
        if (video.snippet.liveBroadcastContent === 'none') {
          // Exclude live videos, which we cannot play via youtube-dl
          // See: https://stackoverflow.com/a/66070785/627663
          video_ids += video.id.videoId + ",";
        }
      }

      return gapi.client.youtube.videos.list({
        "part": "snippet,contentDetails,statistics",
        "id": video_ids
      })
      .then(function(response) {
        return response.result.items;
      },
      function(err) { console.error("Execute error", err); });
    },
    function(err) { console.error("Execute error", err); });
  }

  setDisplayMode(display_mode_by_tv_id) {
    return this.perform('post', '/display_mode', display_mode_by_tv_id);
  }

  setAnimationMode(animation_mode) {
    return this.perform('post', '/animation_mode', {animation_mode: animation_mode});
  }

  async perform (method, resource, data) {
    return client({
       method,
       url: resource,
       data,
       headers: {}
     }).then(resp => {
       return resp.data ? resp.data : [];
     })
     .catch(resp => {
       console.log('ajax request failed');
       return {};
     })
  }
}

export default APIClient;
