import { getApiHost } from 'api';

class PlaylistVideo {

  fromProps(props) {
    let thumbnail = props.thumbnail;
    if (props.thumbnail.startsWith('/')) {
      const api_host = getApiHost();
      if (process.env.NODE_ENV === 'development' && window.location.hostname === 'localhost') {
          // 'localhost' indicates we are probably running the npm development server on a laptop / desktop computer
          // via `npm start --prefix app`
          thumbnail = '//' + api_host + thumbnail;
      }
    }

    return {
      // Shared Data
      video_id: props.playlist_video_id,
      thumbnail: thumbnail,
      playlist_video_id: props.playlist_video_id,
      video_url: props.url,
      title: props.title,
      duration: props.duration,

      // Unique Data
      create_date: props.create_date,
      color_mode: props.color_mode,
      status: props.status
    };
  }

  fromArray(video_props) {
    var videos = video_props.map((props) => {
      return PlaylistVideo.prototype.fromProps(props);
    });
    return videos;
  }
}

export default PlaylistVideo.prototype;
