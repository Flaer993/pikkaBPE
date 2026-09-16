/* No filesystem or console I/O on the controller. Bound newlib's optional heap. */
#include <errno.h>
#include <stddef.h>
#include <stdint.h>
#include <sys/stat.h>
static unsigned char heap[2048] __attribute__((aligned(8)));
static ptrdiff_t used;
void *_sbrk(ptrdiff_t increment) {
 if(increment<0 || increment>(ptrdiff_t)sizeof(heap)-used) { errno=ENOMEM; return (void*)-1; }
 void *result=&heap[used]; used+=increment; return result;
}
int _write(int fd,const char *data,int count) { (void)fd;(void)data;(void)count;errno=EBADF;return -1; }
int _read(int fd,char *data,int count) { (void)fd;(void)data;(void)count;errno=EBADF;return -1; }
int _close(int fd) { (void)fd;errno=EBADF;return -1; }
int _lseek(int fd,int offset,int origin) { (void)fd;(void)offset;(void)origin;errno=EBADF;return -1; }
int _fstat(int fd,struct stat *state) { (void)fd;(void)state;errno=EBADF;return -1; }
int _isatty(int fd) { (void)fd;return 0; }
